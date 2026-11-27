//! USB single-session state machine: detect Mass Storage (054C:0E76), switch to
//! service mode (054C:0336), and expose a RamTransport over the open handle.
//!
//! The service-mode entry and the RAM read/write both ride the on-camera helper
//! (`../target-helper`) via a Sony handshake this MIT build does not ship, so the
//! transport refuses the memory ops until that is wired. Detection and the state
//! machine are real; the memory path is the one deliberate stub.

use rusb::{DeviceHandle, GlobalContext};

use crate::transport::RamTransport;
use crate::{Error, Result};

pub const SONY_VID: u16 = 0x054C;
pub const MSC_PID: u16 = 0x0E76; // Mass Storage
pub const SERVICE_PID: u16 = 0x0336; // service mode (re-enumerated)

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Disconnected,
    MassStorage,
    ServiceMode,
}

pub struct UsbSession {
    handle: Option<DeviceHandle<GlobalContext>>,
    pub state: State,
}

impl UsbSession {
    /// Step 1: find the camera in Mass Storage mode (054C:0E76).
    pub fn detect() -> Result<Self> {
        match rusb::open_device_with_vid_pid(SONY_VID, MSC_PID) {
            Some(h) => Ok(Self { handle: Some(h), state: State::MassStorage }),
            None => Err(Error::Usb(format!(
                "no Sony device at {SONY_VID:04X}:{MSC_PID:04X}. Set the camera USB \
                 mode to Mass Storage."
            ))),
        }
    }

    /// Step 2: switch to service mode (re-enumerates as 054C:0336).
    ///
    /// The vendor handshake that triggers this is provided by Sony-PMCA-RE / the
    /// on-camera helper, which this MIT build does not ship. Wire it here to go live.
    pub fn enter_service(&mut self) -> Result<()> {
        if self.state != State::MassStorage {
            return Err(Error::Usb("not in Mass Storage state".into()));
        }
        Err(Error::Usb(
            "service-mode entry (054C:0E76 -> 054C:0336) needs the PMCA-RE handshake \
             and the on-camera helper, not shipped in this MIT build (see \
             ../target-helper)."
                .into(),
        ))
    }

    pub fn is_open(&self) -> bool {
        self.handle.is_some()
    }
}

/// RamTransport over a service-mode session. Refuses until the on-camera helper is
/// wired — it never guesses at memory it cannot truly reach.
impl RamTransport for UsbSession {
    fn read(&mut self, _addr: u64, _len: usize) -> Result<Vec<u8>> {
        Err(Error::NoTransport)
    }
    fn write(&mut self, _addr: u64, _data: &[u8]) -> Result<()> {
        Err(Error::NoTransport)
    }
}
