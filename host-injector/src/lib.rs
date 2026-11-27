//! opengate-rs — host side of the volatile RAM Open Gate injector (clean-room MIT).
//!
//! Loads the repo's declarative `profiles/*.json`, builds an OGP1 patch blob the
//! on-camera helper (`../target-helper`) consumes, and drives a single-session USB
//! state machine (Mass Storage `054C:0E76` → service mode `054C:0336`) that chains
//! every step in RAM with verify-before-write, readback, and RAII rollback.
//!
//! No Sony firmware bytes: geometry words are arithmetic from the target resolution
//! and live in the JSON; firmware-derived payloads stay in git-ignored `payloads/`.

pub mod descriptor;
pub mod inject;
pub mod profile;
pub mod transport;
pub mod usb;

pub use descriptor::{build_blob, PatchRecord};
pub use inject::{apply_profile, plan, preflight, verify_stock, Dial, PreflightItem, VideoStd};
pub use profile::{Profile, Write};
pub use transport::{NullTransport, RamTransport};

/// Common result type for the crate's application logic.
pub type Result<T> = std::result::Result<T, Error>;

/// One flat error type, so logic stays testable without a USB backend.
#[derive(Debug)]
pub enum Error {
    Io(String),
    Parse(String),
    /// A site did not hold its expected stock bytes (wrong firmware / already patched).
    Stock(String),
    /// Post-write readback did not match the target.
    Readback(String),
    /// No RAM transport is wired (the service-mode helper is not shipped here).
    NoTransport,
    /// USB / device error.
    Usb(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Io(s) => write!(f, "io: {s}"),
            Error::Parse(s) => write!(f, "parse: {s}"),
            Error::Stock(s) => write!(f, "stock check failed: {s}"),
            Error::Readback(s) => write!(f, "readback mismatch: {s}"),
            Error::NoTransport => write!(
                f,
                "no RAM transport wired: the on-camera service-mode helper is not \
                 shipped in this MIT build (see ../target-helper and the README)"
            ),
            Error::Usb(s) => write!(f, "usb: {s}"),
        }
    }
}

impl std::error::Error for Error {}

/// Parse a hex address/number that may carry a `0x` prefix.
pub fn parse_u64(s: &str) -> Result<u64> {
    let t = s.trim();
    let t = t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")).unwrap_or(t);
    u64::from_str_radix(t, 16).map_err(|e| Error::Parse(format!("{s:?}: {e}")))
}

/// Decode a hex byte string (e.g. "000f000a") into bytes.
pub fn parse_hex_bytes(s: &str) -> Result<Vec<u8>> {
    let t = s.trim();
    if t.len() % 2 != 0 {
        return Err(Error::Parse(format!("odd hex length in {s:?}")));
    }
    (0..t.len())
        .step_by(2)
        .map(|i| {
            u8::from_str_radix(&t[i..i + 2], 16)
                .map_err(|e| Error::Parse(format!("{s:?}: {e}")))
        })
        .collect()
}
