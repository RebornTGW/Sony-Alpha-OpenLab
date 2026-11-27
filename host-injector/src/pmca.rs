//! Service-mode link + on-camera helper driver.
//!
//! This is the layer above the generic SCSI BOT (`scsi::MscBot`) that: unlocks Sony
//! service mode, uploads the compiled helper (`libogpatch.so`), feeds it OGP1 blobs,
//! and reads RAM back. The *mechanics* (file put/get, run, readback, the single held
//! session) are implemented here. The *vendor specifics* - the exact service-unlock
//! CDB and the SET_FILE2/GET_FILE2/exec opcodes - come from the public MIT
//! Sony-PMCA-RE project (ma1co) and are NOT reproduced from memory.
//!
//! SAFETY: until those verified constants are filled in, every method that would put
//! bytes on the wire refuses. We never send guessed vendor bytes to a camera.

use crate::descriptor::{build_blob, PatchRecord};
use crate::scsi::{BulkPipe, MscBot};
use crate::transport::RamTransport;
use crate::{Error, Result};

/// Flip to `true` only once the vendor constants below are filled with the values
/// verified against Sony-PMCA-RE. While `false`, the write/exec path refuses.
pub const VENDOR_PROTOCOL_VERIFIED: bool = false;

/// Placeholders for the vendor protocol. Fill from Sony-PMCA-RE before enabling.
mod vendor {
    /// Service-mode unlock CDB (the SCSI vendor command that switches 0E76 -> 0336).
    pub const UNLOCK_CDB: &[u8] = &[];
    /// Helper path on the service RAM disk.
    pub const HELPER_PATH: &str = "/tmp_wbshd/libogpatch.so";
    /// OGP1 blob path the helper reads.
    pub const BLOB_PATH: &str = "/tmp_wbshd/ogpatch.bin";
    /// Result path the helper writes.
    pub const RESULT_PATH: &str = "/tmp_wbshd/ogresult.bin";
}

fn guard(what: &str) -> Error {
    Error::Usb(format!(
        "{what}: Sony service-mode vendor protocol not configured. Fill the verified \
         CDB/opcodes in pmca::vendor from the public MIT Sony-PMCA-RE and set \
         VENDOR_PROTOCOL_VERIFIED=true. Refusing to send unverified vendor bytes."
    ))
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
}

impl<P: BulkPipe> ServiceLink<P> {
    pub fn new(bot: MscBot<P>) -> Self {
        Self { bot, state: LinkState::MassStorage }
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

    /// Step 2: switch to service mode (054C:0E76 -> 054C:0336), same session.
    pub fn enter_service(&mut self) -> Result<()> {
        if !VENDOR_PROTOCOL_VERIFIED || vendor::UNLOCK_CDB.is_empty() {
            return Err(guard("enter_service"));
        }
        let st = self.bot.vendor_out(vendor::UNLOCK_CDB, &[])?;
        if st != 0 {
            return Err(Error::Usb(format!("service unlock status {st}")));
        }
        self.state = LinkState::ServiceMode;
        Ok(())
    }

    /// Step 3a: upload the compiled helper .so to the service RAM disk and load it.
    pub fn upload_helper(&mut self, so_bytes: &[u8]) -> Result<()> {
        if !VENDOR_PROTOCOL_VERIFIED {
            return Err(guard("upload_helper"));
        }
        self.put_file(vendor::HELPER_PATH, so_bytes)?;
        self.state = LinkState::HelperLoaded;
        Ok(())
    }

    /// Step 3b: hand the helper one OGP1 blob and run it; returns Ok on applied.
    pub fn apply_blob(&mut self, blob: &[u8]) -> Result<()> {
        if !VENDOR_PROTOCOL_VERIFIED {
            return Err(guard("apply_blob"));
        }
        self.put_file(vendor::BLOB_PATH, blob)?;
        self.run_helper(vendor::BLOB_PATH, vendor::RESULT_PATH)?;
        let res = self.get_file(vendor::RESULT_PATH, 8)?;
        // helper writes a little-endian i32: >=0 records applied, <0 og_result error.
        let code = i32::from_le_bytes([res[0], res[1], res[2], res[3]]);
        if code < 0 {
            return Err(Error::Usb(format!("helper og_apply failed, code {code}")));
        }
        Ok(())
    }

    // ---- vendor file / exec primitives (PMCA-RE protocol) ------------------
    fn put_file(&mut self, _path: &str, _data: &[u8]) -> Result<()> {
        Err(guard("put_file (SET_FILE2)"))
    }
    fn get_file(&mut self, _path: &str, _len: usize) -> Result<Vec<u8>> {
        Err(guard("get_file (GET_FILE2)"))
    }
    fn run_helper(&mut self, _blob_path: &str, _result_path: &str) -> Result<()> {
        Err(guard("run_helper (exec)"))
    }

    /// Ask the loaded helper to dump a RAM region (write to RESULT_PATH, read back).
    fn read_ram(&mut self, _addr: u64, len: usize) -> Result<Vec<u8>> {
        if !VENDOR_PROTOCOL_VERIFIED {
            return Err(guard("read_ram"));
        }
        self.get_file(vendor::RESULT_PATH, len)
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
