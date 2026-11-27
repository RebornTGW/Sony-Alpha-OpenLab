//! RAM read/write transport abstraction.
//!
//! On BIONZ XR the real read/write is done by the on-camera service-mode helper
//! (`../target-helper`), reached over a USB handshake this MIT build does not ship.
//! So the default transport refuses rather than guesses; tests use an in-memory mock.

use crate::{Error, Result};

pub trait RamTransport {
    fn read(&mut self, addr: u64, len: usize) -> Result<Vec<u8>>;
    fn write(&mut self, addr: u64, data: &[u8]) -> Result<()>;
}

/// Ships no working RAM path: every op refuses with a clean message.
pub struct NullTransport;

impl RamTransport for NullTransport {
    fn read(&mut self, _addr: u64, _len: usize) -> Result<Vec<u8>> {
        Err(Error::NoTransport)
    }
    fn write(&mut self, _addr: u64, _data: &[u8]) -> Result<()> {
        Err(Error::NoTransport)
    }
}

/// Byte-addressable in-memory RAM, for tests. Optionally simulates a bad write at
/// one address (store diverges from the requested bytes) to exercise rollback.
#[derive(Default)]
pub struct MockRam {
    mem: std::collections::HashMap<u64, u8>,
    pub bad_addr: Option<u64>,
}

impl MockRam {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn seed(&mut self, addr: u64, bytes: &[u8]) {
        for (i, b) in bytes.iter().enumerate() {
            self.mem.insert(addr + i as u64, *b);
        }
    }
}

impl RamTransport for MockRam {
    fn read(&mut self, addr: u64, len: usize) -> Result<Vec<u8>> {
        Ok((0..len as u64).map(|i| *self.mem.get(&(addr + i)).unwrap_or(&0)).collect())
    }
    fn write(&mut self, addr: u64, data: &[u8]) -> Result<()> {
        // A "bad" write silently fails to land, so the readback diverges from the
        // target and rollback kicks in (the stored value stays whatever it was).
        if self.bad_addr == Some(addr) {
            return Ok(());
        }
        for (i, b) in data.iter().enumerate() {
            self.mem.insert(addr + i as u64, *b);
        }
        Ok(())
    }
}
