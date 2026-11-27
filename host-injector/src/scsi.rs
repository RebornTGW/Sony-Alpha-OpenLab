//! USB Mass Storage Bulk-Only Transport (BOT), clean-room from the public USB MSC
//! spec. This is the real wire layer: CBW out, optional data phase, CSW in.
//!
//! The bulk pipe is abstracted (`BulkPipe`) so the framing is unit-testable with a
//! fake pipe - no camera needed - while the real path (`UsbPipe`) drives rusb.

use std::time::Duration;

use crate::{Error, Result};

const CBW_SIG: u32 = 0x4342_5355; // "USBC"
const CSW_SIG: u32 = 0x5342_5355; // "USBS"
const CBW_LEN: usize = 31;
const CSW_LEN: usize = 13;

/// Minimal bulk read/write pipe. Implemented for real over rusb, and for tests.
pub trait BulkPipe {
    fn write(&mut self, data: &[u8]) -> Result<usize>;
    fn read(&mut self, buf: &mut [u8]) -> Result<usize>;
}

/// Direction of the data phase.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Dir {
    None,
    In,
    Out,
}

/// SCSI BOT engine over a bulk pipe.
pub struct MscBot<P: BulkPipe> {
    pipe: P,
    tag: u32,
}

impl<P: BulkPipe> MscBot<P> {
    pub fn new(pipe: P) -> Self {
        Self { pipe, tag: 0 }
    }

    fn next_tag(&mut self) -> u32 {
        self.tag = self.tag.wrapping_add(1);
        self.tag
    }

    fn send_cbw(&mut self, cdb: &[u8], data_len: u32, dir: Dir) -> Result<u32> {
        if cdb.is_empty() || cdb.len() > 16 {
            return Err(Error::Usb(format!("bad CDB length {}", cdb.len())));
        }
        let tag = self.next_tag();
        let flags: u8 = if dir == Dir::In { 0x80 } else { 0x00 };
        let mut cbw = Vec::with_capacity(CBW_LEN);
        cbw.extend_from_slice(&CBW_SIG.to_le_bytes());
        cbw.extend_from_slice(&tag.to_le_bytes());
        cbw.extend_from_slice(&data_len.to_le_bytes());
        cbw.push(flags);
        cbw.push(0); // LUN 0
        cbw.push(cdb.len() as u8);
        cbw.extend_from_slice(cdb);
        cbw.resize(CBW_LEN, 0); // pad CDB to 16 -> total 31
        let n = self.pipe.write(&cbw)?;
        if n != CBW_LEN {
            return Err(Error::Usb(format!("short CBW write ({n}/{CBW_LEN})")));
        }
        Ok(tag)
    }

    fn recv_csw(&mut self, tag: u32) -> Result<u8> {
        let mut csw = [0u8; CSW_LEN];
        let n = self.pipe.read(&mut csw)?;
        if n != CSW_LEN {
            return Err(Error::Usb(format!("short CSW read ({n}/{CSW_LEN})")));
        }
        let sig = u32::from_le_bytes([csw[0], csw[1], csw[2], csw[3]]);
        let rtag = u32::from_le_bytes([csw[4], csw[5], csw[6], csw[7]]);
        if sig != CSW_SIG {
            return Err(Error::Usb("bad CSW signature".into()));
        }
        if rtag != tag {
            return Err(Error::Usb(format!("CSW tag {rtag} != CBW tag {tag}")));
        }
        Ok(csw[12]) // 0 = passed, 1 = failed, 2 = phase error
    }

    /// One command with a data-IN phase. Returns (scsi_status, data).
    pub fn command_in(&mut self, cdb: &[u8], data_len: usize) -> Result<(u8, Vec<u8>)> {
        let tag = self.send_cbw(cdb, data_len as u32, Dir::In)?;
        let mut data = vec![0u8; data_len];
        let mut got = 0;
        if data_len > 0 {
            got = self.pipe.read(&mut data)?;
            data.truncate(got);
        }
        let status = self.recv_csw(tag)?;
        let _ = got;
        Ok((status, data))
    }

    /// One command with a data-OUT phase. Returns scsi_status.
    pub fn command_out(&mut self, cdb: &[u8], data: &[u8]) -> Result<u8> {
        let tag = self.send_cbw(cdb, data.len() as u32, Dir::Out)?;
        if !data.is_empty() {
            let n = self.pipe.write(data)?;
            if n != data.len() {
                return Err(Error::Usb(format!("short data-out ({n}/{})", data.len())));
            }
        }
        self.recv_csw(tag)
    }

    /// SCSI INQUIRY (read-only). Returns (vendor, product, rev) on success.
    pub fn inquiry(&mut self) -> Result<(String, String, String)> {
        let (st, d) = self.command_in(&[0x12, 0, 0, 0, 36, 0], 36)?;
        if st != 0 || d.len() < 36 {
            return Err(Error::Usb(format!("INQUIRY status {st}, {} bytes", d.len())));
        }
        let s = |a: usize, b: usize| String::from_utf8_lossy(&d[a..b]).trim().to_string();
        Ok((s(8, 16), s(16, 32), s(32, 36)))
    }

    /// SCSI TEST UNIT READY (read-only). Returns the status byte.
    pub fn test_unit_ready(&mut self) -> Result<u8> {
        let (st, _) = self.command_in(&[0, 0, 0, 0, 0, 0], 0)?;
        Ok(st)
    }

    /// SCSI READ CAPACITY(10) (read-only). Returns (last_lba, block_bytes).
    pub fn read_capacity10(&mut self) -> Result<(u32, u32)> {
        let (st, d) = self.command_in(&[0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0], 8)?;
        if st != 0 || d.len() < 8 {
            return Err(Error::Usb(format!("READ CAPACITY status {st}")));
        }
        let lba = u32::from_be_bytes([d[0], d[1], d[2], d[3]]);
        let blk = u32::from_be_bytes([d[4], d[5], d[6], d[7]]);
        Ok((lba, blk))
    }

    /// Raw vendor command (data-IN). Used by the service-mode layer.
    pub fn vendor_in(&mut self, cdb: &[u8], len: usize) -> Result<(u8, Vec<u8>)> {
        self.command_in(cdb, len)
    }

    /// Raw vendor command (data-OUT).
    pub fn vendor_out(&mut self, cdb: &[u8], data: &[u8]) -> Result<u8> {
        self.command_out(cdb, data)
    }

    /// Borrow the underlying pipe (e.g. to reach `UsbPipe`-only methods like
    /// `control_out`, which isn't part of the generic `BulkPipe` trait).
    pub fn pipe(&self) -> &P {
        &self.pipe
    }

    /// Mutable borrow of the underlying pipe (e.g. `UsbPipe::release`).
    pub fn pipe_mut(&mut self) -> &mut P {
        &mut self.pipe
    }
}

// --------------------------------------------------------------------------- //
// Real rusb-backed bulk pipe.
// --------------------------------------------------------------------------- //
use rusb::{DeviceHandle, Direction, GlobalContext, TransferType};

pub struct UsbPipe {
    handle: DeviceHandle<GlobalContext>,
    ep_in: u8,
    ep_out: u8,
    iface: u8,
    timeout: Duration,
}

impl UsbPipe {
    /// Open a device by VID/PID, claim its MSC interface, find the bulk endpoints.
    pub fn open(vid: u16, pid: u16) -> Result<Self> {
        let handle = rusb::open_device_with_vid_pid(vid, pid)
            .ok_or_else(|| Error::Usb(format!("no device {vid:04X}:{pid:04X}")))?;
        let (iface, ep_in, ep_out) = Self::find_bulk(&handle)?;
        let _ = handle.set_auto_detach_kernel_driver(true);
        handle
            .claim_interface(iface)
            .map_err(|e| Error::Usb(format!("claim interface {iface}: {e}")))?;
        Ok(Self { handle, ep_in, ep_out, iface, timeout: Duration::from_secs(5) })
    }

    fn find_bulk(h: &DeviceHandle<GlobalContext>) -> Result<(u8, u8, u8)> {
        let cfg = h
            .device()
            .active_config_descriptor()
            .map_err(|e| Error::Usb(format!("config descriptor: {e}")))?;
        for iface in cfg.interfaces() {
            for desc in iface.descriptors() {
                let mut ep_in = None;
                let mut ep_out = None;
                for ep in desc.endpoint_descriptors() {
                    if ep.transfer_type() != TransferType::Bulk {
                        continue;
                    }
                    match ep.direction() {
                        Direction::In => ep_in = Some(ep.address()),
                        Direction::Out => ep_out = Some(ep.address()),
                    }
                }
                if let (Some(i), Some(o)) = (ep_in, ep_out) {
                    return Ok((desc.interface_number(), i, o));
                }
            }
        }
        Err(Error::Usb("no bulk IN+OUT endpoint pair found".into()))
    }

    pub fn release(&mut self) {
        let _ = self.handle.release_interface(self.iface);
    }

    /// Vendor control-OUT, host-to-device, device recipient (bmRequestType 0x40),
    /// no data stage - used to send StartSenser/StopSenser on the still-open MSC
    /// handle, before the camera re-enumerates under a different PID.
    pub fn control_out(&self, (req, value, index): (u8, u16, u16)) -> Result<()> {
        self.handle
            .write_control(0x40, req, value, index, &[], self.timeout)
            .map(|_| ())
            .map_err(|e| Error::Usb(format!("vendor control-out: {e}")))
    }
}

impl BulkPipe for UsbPipe {
    fn write(&mut self, data: &[u8]) -> Result<usize> {
        self.handle
            .write_bulk(self.ep_out, data, self.timeout)
            .map_err(|e| Error::Usb(format!("bulk out: {e}")))
    }
    fn read(&mut self, buf: &mut [u8]) -> Result<usize> {
        self.handle
            .read_bulk(self.ep_in, buf, self.timeout)
            .map_err(|e| Error::Usb(format!("bulk in: {e}")))
    }
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    /// Scripted bulk pipe: records writes, replays queued read responses.
    struct MockPipe {
        reads: VecDeque<Vec<u8>>,
        last_cbw: Option<Vec<u8>>,
    }
    impl MockPipe {
        fn new(responses: Vec<Vec<u8>>) -> Self {
            Self { reads: responses.into(), last_cbw: None }
        }
    }
    impl BulkPipe for MockPipe {
        fn write(&mut self, data: &[u8]) -> Result<usize> {
            if data.len() == CBW_LEN {
                assert_eq!(&data[0..4], &CBW_SIG.to_le_bytes(), "CBW signature");
                self.last_cbw = Some(data.to_vec());
            }
            Ok(data.len())
        }
        fn read(&mut self, buf: &mut [u8]) -> Result<usize> {
            let r = self.reads.pop_front().expect("unexpected read");
            let n = r.len().min(buf.len());
            buf[..n].copy_from_slice(&r[..n]);
            Ok(n)
        }
    }

    fn csw_ok(tag: u32) -> Vec<u8> {
        let mut c = Vec::new();
        c.extend_from_slice(&CSW_SIG.to_le_bytes());
        c.extend_from_slice(&tag.to_le_bytes());
        c.extend_from_slice(&0u32.to_le_bytes()); // residue
        c.push(0); // status pass
        c
    }

    #[test]
    fn inquiry_parses_vendor_product() {
        let mut data = vec![0u8; 36];
        data[0] = 0x00;
        data[8..16].copy_from_slice(b"Sony    ");
        data[16..32].copy_from_slice(b"Camera Storage  ");
        data[32..36].copy_from_slice(b"1.00");
        let mut bot = MscBot::new(MockPipe::new(vec![data, csw_ok(1)]));
        let (v, p, r) = bot.inquiry().unwrap();
        assert_eq!(v, "Sony");
        assert_eq!(p, "Camera Storage");
        assert_eq!(r, "1.00");
    }

    #[test]
    fn test_unit_ready_reads_status() {
        let mut bot = MscBot::new(MockPipe::new(vec![csw_ok(1)]));
        assert_eq!(bot.test_unit_ready().unwrap(), 0);
    }

    #[test]
    fn read_capacity_decodes_be() {
        let mut cap = Vec::new();
        cap.extend_from_slice(&2047u32.to_be_bytes());
        cap.extend_from_slice(&512u32.to_be_bytes());
        let mut bot = MscBot::new(MockPipe::new(vec![cap, csw_ok(1)]));
        assert_eq!(bot.read_capacity10().unwrap(), (2047, 512));
    }

    #[test]
    fn bad_csw_signature_errors() {
        let bad = vec![0u8; CSW_LEN];
        let mut bot = MscBot::new(MockPipe::new(vec![vec![0u8; 0], bad]));
        assert!(bot.test_unit_ready().is_err());
    }

    #[test]
    fn cbw_tag_increments() {
        let mut bot = MscBot::new(MockPipe::new(vec![csw_ok(1), csw_ok(2)]));
        bot.test_unit_ready().unwrap();
        bot.test_unit_ready().unwrap();
    }
}
