//! A6700 USB entry point: open the camera in Mass Storage mode over rusb and wrap
//! it in a `ServiceLink` (the held single-session link that carries probe, service
//! entry, helper upload, and the RAM read/write + rollback path).

use crate::pmca::ServiceLink;
use crate::scsi::{MscBot, UsbPipe};
use crate::Result;

pub const SONY_VID: u16 = 0x054C;
pub const MSC_PID: u16 = 0x0E76; // Mass Storage
pub const SERVICE_PID: u16 = 0x0336; // service mode (re-enumerated)

/// Open the A6700 in Mass Storage mode and return the service link.
/// Real USB: detection, interface claim, and the read-only SCSI probe all work on
/// hardware now; the service-mode/helper steps refuse until the vendor protocol
/// constants are configured (see `pmca`).
pub fn open_a6700() -> Result<ServiceLink<UsbPipe>> {
    let pipe = UsbPipe::open(SONY_VID, MSC_PID)?;
    Ok(ServiceLink::new(MscBot::new(pipe)))
}
