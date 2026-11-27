//! Service-mode link + on-camera helper driver.
//!
//! Layer above the generic SCSI BOT (`scsi::MscBot`). The Sony USB vendor framing
//! below is transcribed CLEAN-ROOM from the public MIT project ma1co/Sony-PMCA-RE
//! (master) - constants and layouts only, reimplemented as original Rust. The raw
//! GitHub files carry no line numbers, so citations are by file + symbol.
//!
//! SAFETY: two gates stand between this code and a real camera.
//!   1. `VENDOR_PROTOCOL_VERIFIED` (compile-time) stays `false` until the path is
//!      proven on a real A6700.
//!   2. a runtime `allow_unverified` flag (CLI `--allow-unverified-usb`, with an
//!      interactive confirm) lets a tester send real frames without recompiling.
//! Even when ungated, steps whose data is EXTERNAL (the Senser key tables + the
//! SHA1-path hash, and the senser bulk backend) refuse rather than guess. There is
//! no `ShellExec` opcode in PMCA-RE: a binary runs via the `SHEL` interactive relay.
//! No fabricated vendor bytes are ever put on the wire.

use crate::descriptor::{build_blob, PatchRecord};
use crate::scsi::{BulkPipe, MscBot};
use crate::transport::RamTransport;
use crate::{Error, Result};

/// Flip to `true` only once the whole path is verified on a real A6700.
pub const VENDOR_PROTOCOL_VERIFIED: bool = false;

/// Sony USB vendor protocol constants, from ma1co/Sony-PMCA-RE (master).
pub mod vendor {
    // --- Mass Storage vendor command (pmca/usb/sony.py, _BaseSonyMscExtCmdDevice) --
    /// SCSI opcode of a Sony vendor command (`MSC_OC_ExtCmd = 0x7a`). The 12-byte
    /// CDB is `[0x7a] + dump32le(cmd) + 7*b'\0'`.
    pub const MSC_OC_EXTCMD: u8 = 0x7a;
    pub const CDB_LEN: usize = 12;
    /// "device busy" sense, retried by the driver (`MSC_SENSE_DeviceBusy`).
    pub const SENSE_BUSY: (u8, u8, u8) = (0x09, 0x81, 0x81);
    /// `ExtCmdHeader` = INT32 dataSize, INT16 cmd, INT16 direction, 8 reserved (16 B).
    /// Default read/write buffer is `0x2000`.
    pub const EXT_HEADER_LEN: usize = 16;
    pub const EXT_BUFFER: usize = 0x2000;

    // --- VID / PIDs (pmca/usb/sony.py + pmca/commands/usb.py) ---------------------
    pub const SONY_VID: u16 = 0x054c; // SONY_ID_VENDOR
    /// `SONY_ID_PRODUCT_SENSER` - service mode. 0x0336 is a DETECTION pid: the camera
    /// re-enumerates to it after the senser handshake; it is not a switch command.
    pub const PID_SENSER: [u16; 2] = [0x02a9, 0x0336];
    /// `SONY_ID_PRODUCT_UPDATER` - firmware-updater mode.
    pub const PID_UPDATER: [u16; 2] = [0x033a, 0x03e2];

    // --- Service (Senser) mode switch -------------------------------------------
    // pmca/commands/usb.py (senserShellCommand) + pmca/usb/sony.py (SonySenserAuthDevice).
    // USB control (vendor) requests, as (request, value, index):
    /// `SONY_VendorRequest_StartSenser = (1, 0x37ff, 0xd7aa)`.
    pub const VREQ_START_SENSER: (u8, u16, u16) = (1, 0x37ff, 0xd7aa);
    /// `SONY_VendorRequest_StopSenser = (1, 0xc800, 0x2855)`.
    pub const VREQ_STOP_SENSER: (u8, u16, u16) = (1, 0xc800, 0x2855);

    // --- Senser packet + file control (pmca/usb/sony.py, SonySenserDevice/Camera) -
    /// `SenserPacketHeader` = size INT32, pFunc INT16, sequence INT16, version INT8,
    /// miconType INT8, offsetType INT8, response INT8 (12 B). NOTE: the Struct field
    /// endianness defaults to pmca/util (not fetched); assumed little-endian here.
    pub const SENSER_HEADER_LEN: usize = 12;
    pub const SENSER_MIN: usize = 0x200;
    pub const SENSER_CHUNK: usize = 0x8000;
    /// pFunc values: file control and memory dump.
    pub const PFUNC_FILE_CONTROL: u16 = 0xff01;
    pub const PFUNC_MEMORY_DUMP: u16 = 0xff03;
    /// `FileControlHeader` = cmd INT16, filenameSize INT16; filename is latin1 padded
    /// with NUL to a multiple of 4, then the data follows.
    pub const FILE_WRITE: u16 = 1;
    pub const FILE_READ: u16 = 2;
    pub const FILE_DELETE: u16 = 3;
    /// `MemoryDumpHeader` = base INT32, size INT32 (the RAM read path).

    // --- Senser auth handshake (pmca/usb/sony.py, SonySenserAuthDevice) ----------
    /// `AuthPacket` (BIG_ENDIAN) = cmd INT16, salt INT16, data STR(0x200) -> 516 B.
    pub const AUTH_DATA_LEN: usize = 0x200;
    pub const AUTH_PACKET_LEN: usize = 2 + 2 + AUTH_DATA_LEN; // 516
    /// `_sendAuthPacket` sends cmd as `~cmd & 0xffff`, salt always 0; the reply code
    /// is `(~resp.cmd & 0xffff) - resp.salt`.
    pub const AUTH_CMD_CHALLENGE: u16 = 1; // reply 2 (SHA1) or 8 (SHA256)
    pub const AUTH_CMD_RESPONSE: u16 = 3; // body = 0x01 + hash; reply must be 4
    pub const AUTH_CMD_FINISH: u16 = 5; // reply must be 6, then data[0] == 1
    pub const AUTH_REPLY_SHA1: u16 = 2;
    pub const AUTH_REPLY_SHA256: u16 = 8;
    pub const AUTH_REPLY_RESPONSE_OK: u16 = 4;
    pub const AUTH_REPLY_FINISH_OK: u16 = 6;
    pub const AUTH_ROUNDS: usize = 3;
    // The round key `senserKeysSha1[i]`/`senserKeysSha256[i]` is appended to `data`
    // only when the live PID is 0x0336; the hash is `crypto.sha1_faulty` (SHA1 path)
    // or SHA256. See EXTERNAL below - the keys and sha1_faulty are not embedded here.

    // --- Updater/camera shell (pmca/platform/backend/usb/__init__.py) ------------
    /// Shell feature id passed to sendSonyExtCommand (so the MSC CDB is
    /// `0x7a` + LE32(0x23) + 7 zeros). `USB_FEATURE_SHELL = 0x23`.
    pub const USB_FEATURE_SHELL: u32 = 0x23;
    /// `UsbShellRequest` = cmd STR(4) + data STR(0xfff8). `UsbShellResponse` = result
    /// INT32; failure when `result & 0x80000000`.
    pub const SHELL_DATA_MAX: usize = 0xfff8;
    pub const SHELL_RESULT_ERROR_BIT: u32 = 0x8000_0000;
    /// 4-byte ASCII shell command tokens (verbatim from UsbPlatformBackend).
    pub const SHELL_TEST: &[u8; 4] = b"TEST"; // start() probe
    pub const SHELL_SHEL: &[u8; 4] = b"SHEL"; // interactive shell (how a binary is run)
    pub const SHELL_PUSH: &[u8; 4] = b"PUSH"; // writeFile(path): PUSH + usb_transfer_write
    pub const SHELL_PULL: &[u8; 4] = b"PULL"; // readFile(path): PULL (returns size) + read
    pub const SHELL_RMEM: &[u8; 4] = b"RMEM"; // readMemory(offset,size)
    pub const SHELL_EXIT: &[u8; 4] = b"EXIT"; // stop()
    /// `UsbMemoryReadRequest` = offset INT32, size INT32 (the RMEM body).
    /// `UsbSequenceTransferHeader` = sequence INT32 (prefixes each transfer message).
    /// `UsbDataMsg` = size INT32 + data STR(0xfff8); `UsbStatusMsg` = status INT32
    /// (USB_STATUS_EOF = 1). Endianness of these is the pmca/util default (not
    /// fetched); assumed little-endian - flagged where it matters.
    pub const USB_STATUS_EOF: u32 = 1;

    // --- Our convention for the on-camera files (RAM disk) ----------------------
    pub const HELPER_PATH: &str = "/tmp/libogpatch.so";
    pub const BLOB_PATH: &str = "/tmp/ogpatch.bin";
    pub const RESULT_PATH: &str = "/tmp/ogresult.bin";

    // --- EXTERNAL (MIT, present in Sony-PMCA-RE, NOT embedded in this repo) -------
    // * Senser key tables: `pmca/usb/constants.py` -> `senserKeysSha1` /
    //   `senserKeysSha256`, each a list of 3 opaque byte blobs (hundreds of bytes;
    //   SHA1 entries longer than SHA256). Reused by index 0..2 per auth round.
    // * `crypto.sha1_faulty` (pmca/usb/crypto.py) - the SHA1-path hash function.
    // * The senser bulk transport lives in `pmca/platform/backend/senser.py`.
    // These are referenced, not copied; supply them locally to run auth for real.
    // There is NO dedicated "ShellExec" opcode: a binary is run via the `SHEL`
    // interactive shell relay (pmca/shell/interactive.py, 127.0.0.1:5005).
}

// ----------------------- pure vendor frame builders ------------------------- //
// These serialize the cited layouts and are unit-tested. They build bytes only;
// nothing here touches a device.

/// 12-byte Sony MSC vendor CDB: `[0x7a] + cmd(LE32) + 7*0x00`.
pub fn msc_cdb(cmd: u32) -> [u8; vendor::CDB_LEN] {
    let mut c = [0u8; vendor::CDB_LEN];
    c[0] = vendor::MSC_OC_EXTCMD;
    c[1..5].copy_from_slice(&cmd.to_le_bytes());
    c
}

/// 16-byte ExtCmdHeader: INT32 dataSize, INT16 cmd, INT16 direction, 8 reserved.
pub fn ext_header(data_size: u32, cmd: u16, direction: u16) -> [u8; vendor::EXT_HEADER_LEN] {
    let mut h = [0u8; vendor::EXT_HEADER_LEN];
    h[0..4].copy_from_slice(&data_size.to_le_bytes());
    h[4..6].copy_from_slice(&cmd.to_le_bytes());
    h[6..8].copy_from_slice(&direction.to_le_bytes());
    h
}

/// Wrap a body in a SenserPacketHeader (size, pFunc, sequence, 4x INT8 = 0).
fn senser_wrap(pfunc: u16, sequence: u16, body: &[u8]) -> Vec<u8> {
    let size = (vendor::SENSER_HEADER_LEN + body.len()) as u32;
    let mut f = Vec::with_capacity(size as usize);
    f.extend_from_slice(&size.to_le_bytes());
    f.extend_from_slice(&pfunc.to_le_bytes());
    f.extend_from_slice(&sequence.to_le_bytes());
    f.extend_from_slice(&[0u8, 0, 0, 0]); // version, miconType, offsetType, response
    f.extend_from_slice(body);
    f
}

/// Senser FileControl frame: header + (cmd, filenameSize) + padded filename + data.
pub fn senser_file_frame(sub_cmd: u16, path: &str, data: &[u8], sequence: u16) -> Vec<u8> {
    let name = path.as_bytes();
    let padded = (name.len() + 3) & !3;
    let mut body = Vec::with_capacity(4 + padded + data.len());
    body.extend_from_slice(&sub_cmd.to_le_bytes());
    body.extend_from_slice(&(name.len() as u16).to_le_bytes());
    body.extend_from_slice(name);
    body.resize(4 + padded, 0); // NUL-pad filename to a multiple of 4
    body.extend_from_slice(data);
    senser_wrap(vendor::PFUNC_FILE_CONTROL, sequence, &body)
}

/// Senser MemoryDump frame: header + (base INT32, size INT32).
pub fn senser_memdump_frame(base: u32, size: u32, sequence: u16) -> Vec<u8> {
    let mut body = Vec::with_capacity(8);
    body.extend_from_slice(&base.to_le_bytes());
    body.extend_from_slice(&size.to_le_bytes());
    senser_wrap(vendor::PFUNC_MEMORY_DUMP, sequence, &body)
}

/// Senser AuthPacket (BIG_ENDIAN): cmd INT16 (sent as `~cmd & 0xffff`), salt INT16
/// (always 0), data STR(0x200) NUL-padded / truncated. Total 516 bytes.
pub fn auth_packet(cmd: u16, data: &[u8]) -> Vec<u8> {
    let mut f = Vec::with_capacity(vendor::AUTH_PACKET_LEN);
    f.extend_from_slice(&(!cmd).to_be_bytes()); // ~cmd & 0xffff, big-endian
    f.extend_from_slice(&0u16.to_be_bytes()); // salt = 0
    let mut d = data.to_vec();
    d.resize(vendor::AUTH_DATA_LEN, 0); // pad / truncate to 0x200
    f.extend_from_slice(&d[..vendor::AUTH_DATA_LEN]);
    f
}

/// Decode an AuthPacket reply code: `(~resp.cmd & 0xffff) - resp.salt` (big-endian).
pub fn auth_reply_code(reply: &[u8]) -> Option<u16> {
    if reply.len() < 4 {
        return None;
    }
    let cmd = u16::from_be_bytes([reply[0], reply[1]]);
    let salt = u16::from_be_bytes([reply[2], reply[3]]);
    Some((!cmd).wrapping_sub(salt))
}

/// Updater-shell request: 4-byte token + data NUL-padded to 0xfff8
/// (`UsbShellRequest`). Carried over USB_FEATURE_SHELL (0x23).
pub fn shell_request(token: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut f = Vec::with_capacity(4 + vendor::SHELL_DATA_MAX);
    f.extend_from_slice(token);
    let mut d = data.to_vec();
    d.resize(vendor::SHELL_DATA_MAX, 0);
    f.extend_from_slice(&d[..vendor::SHELL_DATA_MAX]);
    f
}

/// RMEM body: `UsbMemoryReadRequest` = offset INT32, size INT32. Endianness is the
/// pmca/util default (unverified); little-endian assumed.
pub fn mem_read_request(offset: u32, size: u32) -> [u8; 8] {
    let mut b = [0u8; 8];
    b[0..4].copy_from_slice(&offset.to_le_bytes());
    b[4..8].copy_from_slice(&size.to_le_bytes());
    b
}

/// `UsbSequenceTransferHeader` = sequence INT32 (prefixes each transfer message).
pub fn seq_header(sequence: u32) -> [u8; 4] {
    sequence.to_le_bytes()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkState {
    MassStorage,
    ServiceMode,
    HelperLoaded,
}

/// A single held USB session: Mass Storage -> service mode -> helper -> RAM ops.
pub struct ServiceLink<P: BulkPipe> {
    bot: MscBot<P>,
    pub state: LinkState,
    allow_unverified: bool,
}

impl<P: BulkPipe> ServiceLink<P> {
    pub fn new(bot: MscBot<P>) -> Self {
        Self { bot, state: LinkState::MassStorage, allow_unverified: false }
    }

    /// Let a tester send real vendor frames without recompiling (CLI
    /// `--allow-unverified-usb`). Off by default.
    pub fn set_allow_unverified(&mut self, allow: bool) {
        self.allow_unverified = allow;
    }

    /// The two-stage gate: compile-time verified OR runtime opt-in.
    fn gate(&self, what: &str) -> Result<()> {
        if VENDOR_PROTOCOL_VERIFIED || self.allow_unverified {
            Ok(())
        } else {
            Err(Error::Usb(format!(
                "{what}: USB vendor path is guarded (never run on an A6700). Re-run \
                 with --allow-unverified-usb to send real frames at your own risk."
            )))
        }
    }

    /// Read-only SCSI probe (works on real hardware today - no vendor magic).
    pub fn probe(&mut self) -> Result<()> {
        let (v, p, r) = self.bot.inquiry()?;
        println!("[probe ] INQUIRY vendor={v:?} product={p:?} rev={r:?}");
        let tur = self.bot.test_unit_ready()?;
        println!("[probe ] TEST UNIT READY status {tur}");
        match self.bot.read_capacity10() {
            Ok((lba, blk)) => println!("[probe ] READ CAPACITY {} x {blk} B", lba + 1),
            Err(e) => println!("[probe ] READ CAPACITY: {e}"),
        }
        Ok(())
    }

    /// Step 2: enter service (senser) mode. Framing is modelled (AuthPacket, the
    /// 3-round challenge/response from SonySenserAuthDevice.authenticate), but the
    /// round keys and the SHA1-path hash are external (see EXTERNAL in `vendor`).
    pub fn enter_service(&mut self) -> Result<()> {
        self.gate("enter_service")?;
        // Round 1 challenge would be sent as this packet (cmd 1):
        let _challenge = auth_packet(vendor::AUTH_CMD_CHALLENGE, &[]);
        Err(Error::Usb(
            "enter_service: handshake framing is ready (pmca/usb/sony.py \
             SonySenserAuthDevice: AuthPacket, _sendAuthPacket, authenticate), but the \
             round keys `senserKeysSha1`/`senserKeysSha256` (pmca/usb/constants.py) and \
             `crypto.sha1_faulty` (pmca/usb/crypto.py) are external MIT data, not \
             embedded here. Supply them locally to complete auth."
                .into(),
        ))
    }

    /// Step 3a: push the compiled helper to the camera (updater shell `PUSH`, then
    /// usb_transfer_write). Request framing is built; the send needs a connected shell.
    pub fn upload_helper(&mut self, so_bytes: &[u8]) -> Result<()> {
        self.gate("upload_helper")?;
        let _req = shell_request(vendor::SHELL_PUSH, vendor::HELPER_PATH.as_bytes());
        let _ = so_bytes; // body streams via usb_transfer_write (transfer.py UsbDataMsg)
        Err(Error::Usb(
            "upload_helper: PUSH framing is ready (pmca/platform/backend/usb \
             UsbPlatformBackend.writeFile, token b'PUSH'), but it needs a connected \
             shell (token b'TEST'), which needs service mode - blocked on enter_service."
                .into(),
        ))
    }

    /// Step 3b: PUSH the OGP1 blob, then run the helper. NOTE: there is no exec
    /// opcode - a binary runs via the `SHEL` interactive relay.
    pub fn apply_blob(&mut self, blob: &[u8]) -> Result<()> {
        self.gate("apply_blob")?;
        let _push = shell_request(vendor::SHELL_PUSH, vendor::BLOB_PATH.as_bytes());
        let _ = blob;
        let _shel = shell_request(vendor::SHELL_SHEL, &[]);
        Err(Error::Usb(
            "apply_blob: no ShellExec opcode exists in PMCA-RE; a binary is run via the \
             b'SHEL' interactive relay (pmca/shell/interactive.py). That needs a \
             connected shell (enter_service first)."
                .into(),
        ))
    }

    /// Read a RAM region back (updater shell `RMEM`, UsbMemoryReadRequest). Framing is
    /// built; the send needs a connected shell.
    fn read_ram(&mut self, addr: u64, len: usize) -> Result<Vec<u8>> {
        self.gate("read_ram")?;
        let _req = shell_request(vendor::SHELL_RMEM, &mem_read_request(addr as u32, len as u32));
        Err(Error::Usb(
            "read_ram: RMEM framing is ready (pmca/platform/backend/usb \
             UsbPlatformBackend.readMemory, token b'RMEM'), but it needs a connected \
             shell - blocked on enter_service."
                .into(),
        ))
    }
}

/// A `ServiceLink` IS a RAM transport: the SessionGuard's read/verify/write/readback
/// and its RAII rollback all run straight over the held service-mode session.
impl<P: BulkPipe> RamTransport for ServiceLink<P> {
    fn read(&mut self, addr: u64, len: usize) -> Result<Vec<u8>> {
        self.read_ram(addr, len)
    }

    fn write(&mut self, addr: u64, data: &[u8]) -> Result<()> {
        // Re-read current bytes as the helper's stock guard, then apply one record.
        let stock = self.read_ram(addr, data.len())?;
        let rec = PatchRecord { vaddr: addr, flags: 0, stock, target: data.to_vec() };
        let blob = build_blob(&[rec]);
        self.apply_blob(&blob)
    }
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn msc_cdb_is_0x7a_plus_le32() {
        let cdb = msc_cdb(0x0000_0030); // e.g. a command id
        assert_eq!(cdb.len(), 12);
        assert_eq!(cdb[0], 0x7a);
        assert_eq!(&cdb[1..5], &[0x30, 0x00, 0x00, 0x00]); // little-endian
        assert_eq!(&cdb[5..12], &[0u8; 7]); // 7 trailing zeros
    }

    #[test]
    fn ext_header_layout() {
        let h = ext_header(0x1234, 0x0007, 0x0001);
        assert_eq!(&h[0..4], &0x1234u32.to_le_bytes());
        assert_eq!(&h[4..6], &0x0007u16.to_le_bytes());
        assert_eq!(&h[6..8], &0x0001u16.to_le_bytes());
        assert_eq!(&h[8..16], &[0u8; 8]);
    }

    #[test]
    fn senser_file_frame_writes_header_name_data() {
        let data = [0xAAu8, 0xBB];
        let f = senser_file_frame(vendor::FILE_WRITE, "/tmp/x", &data, 1);
        // header: size(4) pfunc(2) seq(2) + 4 zero bytes
        let size = u32::from_le_bytes([f[0], f[1], f[2], f[3]]) as usize;
        assert_eq!(size, f.len());
        assert_eq!(u16::from_le_bytes([f[4], f[5]]), vendor::PFUNC_FILE_CONTROL);
        assert_eq!(u16::from_le_bytes([f[6], f[7]]), 1); // sequence
        // body: cmd(2) nameLen(2) name(padded to 4) data
        let b = &f[vendor::SENSER_HEADER_LEN..];
        assert_eq!(u16::from_le_bytes([b[0], b[1]]), vendor::FILE_WRITE);
        assert_eq!(u16::from_le_bytes([b[2], b[3]]), 6); // len("/tmp/x")
        assert_eq!(&b[4..10], b"/tmp/x");
        // "/tmp/x" is 6 bytes -> padded to 8; data follows at body offset 4+8
        assert_eq!(&b[4 + 8..], &data);
    }

    #[test]
    fn senser_memdump_frame_packs_base_size() {
        let f = senser_memdump_frame(0x4010_0000, 0x40, 2);
        assert_eq!(u16::from_le_bytes([f[4], f[5]]), vendor::PFUNC_MEMORY_DUMP);
        let b = &f[vendor::SENSER_HEADER_LEN..];
        assert_eq!(u32::from_le_bytes([b[0], b[1], b[2], b[3]]), 0x4010_0000);
        assert_eq!(u32::from_le_bytes([b[4], b[5], b[6], b[7]]), 0x40);
    }

    #[test]
    fn guarded_until_opt_in() {
        // Build a link over a dummy pipe; gate refuses, then opt-in flips to a GAP.
        struct Dead;
        impl BulkPipe for Dead {
            fn write(&mut self, d: &[u8]) -> Result<usize> {
                Ok(d.len())
            }
            fn read(&mut self, _b: &mut [u8]) -> Result<usize> {
                Err(Error::Usb("no device".into()))
            }
        }
        let mut link = ServiceLink::new(MscBot::new(Dead));
        let e1 = link.enter_service().unwrap_err();
        assert!(matches!(e1, Error::Usb(ref s) if s.contains("guarded")));
        link.set_allow_unverified(true);
        let e2 = link.enter_service().unwrap_err();
        // ungated, but still refuses because the round keys are external (EXTERNAL).
        assert!(matches!(e2, Error::Usb(ref s) if s.contains("senserKeys")));
    }

    #[test]
    fn auth_packet_is_516_be_complemented_cmd() {
        let p = auth_packet(vendor::AUTH_CMD_CHALLENGE, b"hi");
        assert_eq!(p.len(), vendor::AUTH_PACKET_LEN); // 516
        // cmd sent as ~cmd & 0xffff, big-endian
        assert_eq!(&p[0..2], &(!vendor::AUTH_CMD_CHALLENGE).to_be_bytes());
        assert_eq!(&p[2..4], &0u16.to_be_bytes()); // salt 0
        assert_eq!(&p[4..6], b"hi"); // data, then NUL padding
        assert_eq!(p[6], 0);
    }

    #[test]
    fn auth_reply_code_decodes() {
        // reply cmd=~2, salt=0 -> code 2 (SHA1 path)
        let mut r = Vec::new();
        r.extend_from_slice(&(!2u16).to_be_bytes());
        r.extend_from_slice(&0u16.to_be_bytes());
        assert_eq!(auth_reply_code(&r), Some(2));
    }

    #[test]
    fn shell_request_token_and_pad() {
        let req = shell_request(vendor::SHELL_PUSH, b"/tmp/x");
        assert_eq!(req.len(), 4 + vendor::SHELL_DATA_MAX);
        assert_eq!(&req[0..4], b"PUSH");
        assert_eq!(&req[4..10], b"/tmp/x");
        assert_eq!(req[10], 0); // NUL padded
    }

    #[test]
    fn mem_read_request_packs_le() {
        let b = mem_read_request(0x4010_0000, 0x40);
        assert_eq!(u32::from_le_bytes([b[0], b[1], b[2], b[3]]), 0x4010_0000);
        assert_eq!(u32::from_le_bytes([b[4], b[5], b[6], b[7]]), 0x40);
        assert_eq!(seq_header(7), 7u32.to_le_bytes());
    }
}
