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

    // --- Senser key tables (pmca/usb/constants.py) ------------------------------
    // `senserKeysSha1` / `senserKeysSha256` are each a list of 3 byte blobs (hundreds
    // of bytes; SHA1 entries longer than SHA256), reused by index 0..2 per auth round.
    // The full blobs are EXTERNAL MIT data - too large to hand-transcribe safely, so
    // they are NOT embedded. Supply them from a local copy of constants.py; the loaded
    // bytes are checked against these first-8-byte fingerprints (read from the file).
    pub const SENSER_KEY_SHA1_FP: [[u8; 8]; 3] = [
        [0x7d, 0x02, 0x84, 0x1e, 0x0e, 0xed, 0xdb, 0x2f],
        [0xd6, 0xfd, 0xf3, 0x74, 0x6c, 0xba, 0xa9, 0x47],
        [0x58, 0xdc, 0x5d, 0xf6, 0xe5, 0xc3, 0xb0, 0x03],
    ];
    pub const SENSER_KEY_SHA256_FP: [[u8; 8]; 3] = [
        [0xe6, 0x06, 0xab, 0xc6, 0x5e, 0x0d, 0x92, 0xc1],
        [0x37, 0xc4, 0xb1, 0x1c, 0x7e, 0xa1, 0x0d, 0xa1],
        [0x36, 0x84, 0x9b, 0x20, 0xb8, 0x7d, 0x30, 0x9c],
    ];
}

/// SHA-1 + Sony's `sha1_faulty`, ported from ma1co/Sony-PMCA-RE `pmca/usb/crypto.py`
/// (whose header cites github.com/ajalt/python-sha1). The only deviation from stock
/// SHA-1 is the fault: the 64-bit length field encodes `(len(message) & 0x1f) * 8`
/// bits instead of `len(message) * 8`; padding is still from the real length.
pub mod crypto {
    fn sha1_core(message: &[u8], encoded_len_bytes: u64) -> [u8; 20] {
        let mut msg = message.to_vec();
        let ml_bits = encoded_len_bytes.wrapping_mul(8);
        msg.push(0x80);
        while msg.len() % 64 != 56 {
            msg.push(0);
        }
        msg.extend_from_slice(&ml_bits.to_be_bytes());

        let mut h: [u32; 5] = [0x6745_2301, 0xEFCD_AB89, 0x98BA_DCFE, 0x1032_5476, 0xC3D2_E1F0];
        for chunk in msg.chunks(64) {
            let mut w = [0u32; 80];
            for i in 0..16 {
                w[i] = u32::from_be_bytes([chunk[4 * i], chunk[4 * i + 1], chunk[4 * i + 2], chunk[4 * i + 3]]);
            }
            for i in 16..80 {
                w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
            }
            let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
            for (i, &wi) in w.iter().enumerate() {
                let (f, k) = if i < 20 {
                    ((b & c) | ((!b) & d), 0x5A82_7999u32)
                } else if i < 40 {
                    (b ^ c ^ d, 0x6ED9_EBA1)
                } else if i < 60 {
                    ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC)
                } else {
                    (b ^ c ^ d, 0xCA62_C1D6)
                };
                let tmp = a
                    .rotate_left(5)
                    .wrapping_add(f)
                    .wrapping_add(e)
                    .wrapping_add(k)
                    .wrapping_add(wi);
                e = d;
                d = c;
                c = b.rotate_left(30);
                b = a;
                a = tmp;
            }
            h[0] = h[0].wrapping_add(a);
            h[1] = h[1].wrapping_add(b);
            h[2] = h[2].wrapping_add(c);
            h[3] = h[3].wrapping_add(d);
            h[4] = h[4].wrapping_add(e);
        }
        let mut out = [0u8; 20];
        for i in 0..5 {
            out[4 * i..4 * i + 4].copy_from_slice(&h[i].to_be_bytes());
        }
        out
    }

    /// Standard SHA-1.
    pub fn sha1(message: &[u8]) -> [u8; 20] {
        sha1_core(message, message.len() as u64)
    }

    /// Sony's faulty SHA-1: `sha1(message, len(message) & 0x1f)`.
    pub fn sha1_faulty(message: &[u8]) -> [u8; 20] {
        sha1_core(message, (message.len() as u64) & 0x1f)
    }
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

/// A shell command line typed over the `SHEL` raw relay (bytes + newline, latin1).
/// PMCA-RE has NO exec opcode: a binary is run by typing its path on the SHEL pipe
/// (pmca/shell/interactive.py writes `stdin.readline()` straight to the socket).
pub fn helper_invocation(path: &str) -> Vec<u8> {
    let mut v = path.as_bytes().to_vec();
    v.push(b'\n');
    v
}

/// Check a supplied Senser key blob against its cited first-8-byte fingerprint.
pub fn key_fingerprint_ok(key: &[u8], fp: &[u8; 8]) -> bool {
    key.len() >= 8 && &key[..8] == fp
}

/// SHA1-path auth response body (sony.py authenticate): `0x01 + sha1_faulty(input)`,
/// where `input = round_data + key` when the live PID is 0x0336, else `round_data[:4]`.
pub fn senser_response_sha1(round_data: &[u8], key: &[u8], pid: u16) -> Vec<u8> {
    let input: Vec<u8> = if pid == vendor::PID_SENSER[1] {
        let mut v = round_data.to_vec();
        v.extend_from_slice(key);
        v
    } else {
        round_data.iter().take(4).copied().collect()
    };
    let mut out = vec![0x01u8];
    out.extend_from_slice(&crypto::sha1_faulty(&input));
    out
}

/// The three Senser key blobs per hash (copied from pmca/usb/constants.py by the
/// user; verified against the cited fingerprints before use).
pub struct SenserKeys {
    pub sha1: [Vec<u8>; 3],
    pub sha256: [Vec<u8>; 3],
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
    keys: Option<SenserKeys>,
}

impl<P: BulkPipe> ServiceLink<P> {
    pub fn new(bot: MscBot<P>) -> Self {
        Self { bot, state: LinkState::MassStorage, allow_unverified: false, keys: None }
    }

    /// Let a tester send real vendor frames without recompiling (CLI
    /// `--allow-unverified-usb`). Off by default.
    pub fn set_allow_unverified(&mut self, allow: bool) {
        self.allow_unverified = allow;
    }

    /// Supply the Senser key tables (copied by the user from pmca/usb/constants.py).
    /// Each blob is checked against its cited fingerprint before it is stored.
    pub fn set_senser_keys(&mut self, keys: SenserKeys) -> Result<()> {
        for i in 0..3 {
            if !key_fingerprint_ok(&keys.sha1[i], &vendor::SENSER_KEY_SHA1_FP[i]) {
                return Err(Error::Usb(format!("senserKeysSha1[{i}] fingerprint mismatch")));
            }
            if !key_fingerprint_ok(&keys.sha256[i], &vendor::SENSER_KEY_SHA256_FP[i]) {
                return Err(Error::Usb(format!("senserKeysSha256[{i}] fingerprint mismatch")));
            }
        }
        self.keys = Some(keys);
        Ok(())
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
        if self.keys.is_none() {
            return Err(Error::Usb(
                "enter_service: Senser key tables not loaded. Copy senserKeysSha1 / \
                 senserKeysSha256 from pmca/usb/constants.py and pass them to \
                 set_senser_keys() (checked against the cited fingerprints)."
                    .into(),
            ));
        }
        // Keys + hash (crypto::sha1_faulty) + response framing (senser_response_sha1)
        // are ready; round 1 challenge = auth_packet(1). What is missing is the senser
        // control-transfer transport (vendorRequestOut + the ep1 terminal of
        // SonySenserAuthDevice), which this MSC-bulk host does not implement.
        let _challenge = auth_packet(vendor::AUTH_CMD_CHALLENGE, &[]);
        Err(Error::Usb(
            "enter_service: keys loaded and handshake/crypto ready, but the Senser \
             control-transfer transport (vendorRequestOut + ep1 terminal, \
             pmca/usb/sony.py SonySenserAuthDevice) is not implemented on this MSC-bulk \
             host. That is the remaining hardware-integration step."
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

    /// Step 3b: PUSH the OGP1 blob to /tmp, then run the helper by typing its path on
    /// the `SHEL` interactive relay (there is no exec opcode in PMCA-RE). Returns the
    /// ordered frames the sequence emits.
    pub fn apply_blob(&mut self, blob: &[u8]) -> Result<()> {
        self.gate("apply_blob")?;
        let _frames = self.exec_helper_sequence(blob);
        Err(Error::Usb(
            "apply_blob: PUSH->SHEL exec sequence is built (PUSH the blob, open SHEL, \
             type the helper path), but it needs a connected shell - blocked on \
             enter_service."
                .into(),
        ))
    }

    /// Build the ordered frames to push the OGP1 blob and invoke the helper over SHEL:
    /// [PUSH blob req, blob bytes, SHEL req, invocation line]. No exec opcode is used -
    /// the last frame is the plain command line typed on the relay.
    pub fn exec_helper_sequence(&self, blob: &[u8]) -> Vec<Vec<u8>> {
        vec![
            shell_request(vendor::SHELL_PUSH, vendor::BLOB_PATH.as_bytes()),
            blob.to_vec(),
            shell_request(vendor::SHELL_SHEL, &[]),
            helper_invocation(vendor::HELPER_PATH),
        ]
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

    #[test]
    fn sha1_known_vector_abc() {
        // FIPS 180 example SHA-1("abc"). len 3 < 32 -> sha1_faulty equals standard.
        let want: [u8; 20] = [
            0xa9, 0x99, 0x3e, 0x36, 0x47, 0x06, 0x81, 0x6a, 0xba, 0x3e, 0x25, 0x71, 0x78, 0x50,
            0xc2, 0x6c, 0x9c, 0xd0, 0xd8, 0x9d,
        ];
        assert_eq!(crypto::sha1(b"abc"), want);
        assert_eq!(crypto::sha1_faulty(b"abc"), want);
    }

    #[test]
    fn sha1_faulty_diverges_from_32_bytes() {
        // len 32 -> (len & 0x1f) == 0 -> length field differs from standard SHA-1.
        let msg = [0x41u8; 32];
        assert_ne!(crypto::sha1_faulty(&msg), crypto::sha1(&msg));
    }

    #[test]
    fn senser_response_uses_faulty_sha1() {
        let data = [1u8, 2, 3, 4, 5];
        let key = [9u8; 40];
        let r = senser_response_sha1(&data, &key, 0x0336);
        assert_eq!(r[0], 0x01);
        assert_eq!(r.len(), 1 + 20);
        let mut input = data.to_vec();
        input.extend_from_slice(&key); // pid 0x0336 -> data + key
        assert_eq!(&r[1..], &crypto::sha1_faulty(&input));
        let r2 = senser_response_sha1(&data, &key, 0x02a9); // other pid -> data[:4]
        assert_eq!(&r2[1..], &crypto::sha1_faulty(&data[..4]));
    }

    #[test]
    fn key_fingerprint_checks() {
        let good = [0x7d, 0x02, 0x84, 0x1e, 0x0e, 0xed, 0xdb, 0x2f, 0x00, 0x11];
        assert!(key_fingerprint_ok(&good, &vendor::SENSER_KEY_SHA1_FP[0]));
        assert!(!key_fingerprint_ok(&[0u8; 8], &vendor::SENSER_KEY_SHA1_FP[0]));
        assert!(!key_fingerprint_ok(&[0x7d], &vendor::SENSER_KEY_SHA1_FP[0])); // too short
    }

    #[test]
    fn exec_sequence_is_push_then_shel_then_line() {
        struct Dead;
        impl BulkPipe for Dead {
            fn write(&mut self, d: &[u8]) -> Result<usize> {
                Ok(d.len())
            }
            fn read(&mut self, _b: &mut [u8]) -> Result<usize> {
                Err(Error::Usb("x".into()))
            }
        }
        let link = ServiceLink::new(MscBot::new(Dead));
        let f = link.exec_helper_sequence(b"BLOBDATA");
        assert_eq!(f.len(), 4);
        assert_eq!(&f[0][0..4], b"PUSH");
        assert_eq!(&f[1][..], b"BLOBDATA");
        assert_eq!(&f[2][0..4], b"SHEL");
        assert!(f[3].ends_with(b"\n"));
        assert!(f[3].starts_with(b"/tmp/libogpatch.so"));
    }
}
