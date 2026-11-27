//! A6700 USB entry point: open the camera in Mass Storage mode over rusb and wrap
//! it in a `ServiceLink` (the held single-session link that carries probe, service
//! entry, helper upload, and the RAM read/write + rollback path).

use crate::camera::bionz_x_body_name;
use crate::pmca::ServiceLink;
use crate::scsi::{MscBot, UsbPipe};
use crate::{Error, Result};

pub const SONY_VID: u16 = 0x054C;
pub const MSC_PID: u16 = 0x0E76; // Mass Storage
pub const SERVICE_PID: u16 = 0x0336; // service mode (re-enumerated)

/// Open the A6700 in Mass Storage mode and return the service link.
/// Real USB: detection, interface claim, and the read-only SCSI probe all work on
/// hardware now; the service-mode/helper steps refuse until the vendor protocol
/// constants are configured (see `pmca`).
///
/// Every caller - `--plan`, `--verify-only`, `--confirm-ram-write`,
/// `--dump-ram`, everything - goes through this function first, so
/// `refuse_bionz_x_bodies()` runs before any of them can send a single SCSI
/// vendor packet.
pub fn open_a6700() -> Result<ServiceLink<UsbPipe>> {
    refuse_bionz_x_bodies()?;
    let pipe = UsbPipe::open(SONY_VID, MSC_PID)?;
    Ok(ServiceLink::new(MscBot::new(pipe)))
}

/// Scan every currently-connected Sony-VID (`0x054C`) USB device and refuse
/// outright if any of them is a known BIONZ X body (see `camera.rs`'s doc
/// comment for why: this crate's Senser `0x0336` protocol is modeled for
/// BIONZ XR only, and is unverified - likely wrong - on the older BIONZ X
/// generation). Checks the whole bus, not just the PID this crate is about to
/// open, since the hardcoded `MSC_PID` above would never itself be a BIONZ X
/// PID - the real risk is a BIONZ X body being the camera actually plugged
/// in, alongside or instead of an A6700.
fn refuse_bionz_x_bodies() -> Result<()> {
    let devices = rusb::devices().map_err(|e| Error::Usb(format!("enumerate USB devices: {e}")))?;
    for dev in devices.iter() {
        let desc = match dev.device_descriptor() {
            Ok(d) => d,
            Err(_) => continue, // unreadable descriptor - not this crate's concern here
        };
        if desc.vendor_id() != SONY_VID {
            continue;
        }
        if let Some(name) = bionz_x_body_name(desc.product_id()) {
            return Err(Error::Usb(format!(
                "refusing: a BIONZ X body ({name}, PID {:#06x}) is connected. This tool's \
                 Senser 0x0336 service-mode protocol is modeled for BIONZ XR (the A6700's chip) \
                 only and is incompatible with / unverified on BIONZ X hardware - nothing was \
                 sent. For BIONZ X bodies, use multi_exposure.py instead (--raw-blend / \
                 --live-ghost).",
                desc.product_id()
            )));
        }
    }
    Ok(())
}
