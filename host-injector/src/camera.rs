//! Sony camera processor-generation classification.
//!
//! The Senser `0x0336` service-mode protocol this whole crate drives
//! (`pmca.rs`) is modeled for **BIONZ XR** (the A6700's chip) only. BIONZ X
//! bodies (A6400, A6600, A6100, A7 III, A7C, …) are a different, older
//! generation - nothing here has been checked against them, and the project's
//! own clean-room citations (`ma1co/Sony-PMCA-RE`) make no claim either way.
//! Rather than guess, every real-hardware entry point refuses outright the
//! moment a BIONZ X body is detected on the bus, before a single SCSI vendor
//! packet is sent (see `usb::open_a6700`'s `refuse_bionz_x_bodies`).
//!
//! Pure classification only; no USB I/O lives here (that's `usb.rs`), so this
//! is unit-testable without a device or `rusb`.

/// Which processor generation a PID is known to belong to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CameraGeneration {
    /// BIONZ XR - what this crate's Senser `0x0336` protocol targets (A6700
    /// and, per the root README's catalog, the other 13 BIONZ XR bodies).
    BionzXr,
    /// BIONZ X - a different, older generation. Refused outright; see the
    /// module doc comment.
    BionzX,
    /// Not in either known table. Not automatically refused (an unknown PID
    /// might be a BIONZ XR body not yet catalogued), but also not assumed
    /// compatible - callers should still gate real-hardware actions behind
    /// `VENDOR_PROTOCOL_VERIFIED` / `--allow-unverified-usb` as usual.
    Unknown,
}

/// Known BIONZ X body PIDs this crate refuses to touch. "Known incompatible,"
/// not an exhaustive list of every BIONZ X body or every PID it might expose
/// in every USB mode - a PID absent from this table is not thereby confirmed
/// safe, just not specifically flagged (yet).
pub const BIONZ_X_PIDS: &[(u16, &str)] = &[
    (0x0C68, "A6400"),
    (0x0C9F, "A6600"),
    (0x0C9B, "A6100"),
    (0x0C34, "A7 III"),
    (0x0D0A, "A7C"),
];

/// The A6700's own known PIDs (Mass Storage, service/Senser mode, PC Remote) -
/// see `usb::SONY_VID`/`usb::MSC_PID`/`usb::SERVICE_PID`. Duplicated here
/// (rather than imported) so this module has no dependency on `usb.rs` and
/// stays trivially unit-testable; `usb.rs` is the source of truth for the
/// values this crate actually opens by.
pub const BIONZ_XR_PIDS: &[(u16, &str)] = &[
    (0x0E76, "A6700 (Mass Storage)"),
    (0x0E78, "A6700 (PC Remote)"),
    (0x0336, "Senser service mode (re-enumerated, not body-specific)"),
];

/// Classify a Sony-VID PID. Checks the BIONZ X blocklist first, so a PID that
/// (incorrectly) appeared in both tables would still be refused.
pub fn classify_pid(pid: u16) -> CameraGeneration {
    if BIONZ_X_PIDS.iter().any(|(p, _)| *p == pid) {
        return CameraGeneration::BionzX;
    }
    if BIONZ_XR_PIDS.iter().any(|(p, _)| *p == pid) {
        return CameraGeneration::BionzXr;
    }
    CameraGeneration::Unknown
}

/// The body name for a known BIONZ X PID, or `None`.
pub fn bionz_x_body_name(pid: u16) -> Option<&'static str> {
    BIONZ_X_PIDS.iter().find(|(p, _)| *p == pid).map(|(_, name)| *name)
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_every_bionz_x_pid() {
        for &(pid, name) in BIONZ_X_PIDS {
            assert_eq!(classify_pid(pid), CameraGeneration::BionzX, "PID for {name}");
            assert_eq!(bionz_x_body_name(pid), Some(name));
        }
    }

    #[test]
    fn classifies_every_bionz_xr_pid() {
        for &(pid, name) in BIONZ_XR_PIDS {
            assert_eq!(classify_pid(pid), CameraGeneration::BionzXr, "PID for {name}");
            assert_eq!(bionz_x_body_name(pid), None);
        }
    }

    #[test]
    fn unknown_pid_is_neither() {
        let pid = 0xFFFF; // not in either table
        assert_eq!(classify_pid(pid), CameraGeneration::Unknown);
        assert_eq!(bionz_x_body_name(pid), None);
    }

    #[test]
    fn bionz_x_pids_and_bionz_xr_pids_do_not_overlap() {
        for &(x_pid, _) in BIONZ_X_PIDS {
            assert!(
                !BIONZ_XR_PIDS.iter().any(|&(xr_pid, _)| xr_pid == x_pid),
                "PID {x_pid:#06x} listed as both BIONZ X and BIONZ XR"
            );
        }
    }

    #[test]
    fn specific_named_pids_match_the_task_list() {
        // Pin the exact (pid, name) pairs this guard was asked to cover.
        assert_eq!(bionz_x_body_name(0x0C68), Some("A6400"));
        assert_eq!(bionz_x_body_name(0x0C9F), Some("A6600"));
        assert_eq!(bionz_x_body_name(0x0C9B), Some("A6100"));
        assert_eq!(bionz_x_body_name(0x0C34), Some("A7 III"));
        assert_eq!(bionz_x_body_name(0x0D0A), Some("A7C"));
    }
}
