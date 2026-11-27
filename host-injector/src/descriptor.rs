//! OGP1 patch-blob builder (mirrors `../target-helper/include/ogpatch.h`).
//!
//! Turns a profile's geometry writes (those carrying target bytes) into the binary
//! blob the on-camera helper applies. Firmware-derived payload steps are not encoded
//! here: they are referenced by `payload_ref` and supplied separately.

use crate::profile::Profile;
use crate::{Error, Result};

pub const OG_MAGIC: &[u8; 4] = b"OGP1";
pub const OG_FLAG_CODE: u32 = 0x1;

/// One resolved patch record: absolute address, verified stock, target bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PatchRecord {
    pub vaddr: u64,
    pub flags: u32,
    pub stock: Vec<u8>,
    pub target: Vec<u8>,
}

/// Collect every geometry write that has both stock and target bytes.
pub fn records(prof: &Profile) -> Result<Vec<PatchRecord>> {
    let mut out = Vec::new();
    for step in &prof.steps {
        let flags = if step.kind == "code_patch" { OG_FLAG_CODE } else { 0 };
        for w in &step.writes {
            let (stock, target) = match (w.stock_bytes()?, w.target_bytes()?) {
                (Some(s), Some(t)) => (s, t),
                _ => continue, // no target yet (experimental) -> not encodable
            };
            if stock.len() != w.len as usize || target.len() != w.len as usize {
                return Err(Error::Parse(format!(
                    "{} {}: len {} != stock/target byte length",
                    step.id, w.addr, w.len
                )));
            }
            out.push(PatchRecord { vaddr: prof.resolve(w)?, flags, stock, target });
        }
    }
    Ok(out)
}

/// Serialize records into the little-endian OGP1 blob.
pub fn build_blob(recs: &[PatchRecord]) -> Vec<u8> {
    let mut b = Vec::with_capacity(8 + recs.len() * 24);
    b.extend_from_slice(OG_MAGIC);
    b.extend_from_slice(&(recs.len() as u32).to_le_bytes());
    for r in recs {
        b.extend_from_slice(&r.vaddr.to_le_bytes());
        b.extend_from_slice(&(r.stock.len() as u32).to_le_bytes());
        b.extend_from_slice(&r.flags.to_le_bytes());
        b.extend_from_slice(&r.stock);
        b.extend_from_slice(&r.target);
    }
    b
}

/// Parse an OGP1 blob back into records (used by tests / verification).
pub fn parse_blob(blob: &[u8]) -> Result<Vec<PatchRecord>> {
    if blob.len() < 8 || &blob[0..4] != OG_MAGIC {
        return Err(Error::Parse("bad OGP1 magic/header".into()));
    }
    let count = u32::from_le_bytes(blob[4..8].try_into().unwrap()) as usize;
    let mut off = 8;
    let mut out = Vec::with_capacity(count);
    for i in 0..count {
        if off + 16 > blob.len() {
            return Err(Error::Parse(format!("record {i}: truncated header")));
        }
        let vaddr = u64::from_le_bytes(blob[off..off + 8].try_into().unwrap());
        let len = u32::from_le_bytes(blob[off + 8..off + 12].try_into().unwrap()) as usize;
        let flags = u32::from_le_bytes(blob[off + 12..off + 16].try_into().unwrap());
        let body = off + 16;
        if body + len * 2 > blob.len() {
            return Err(Error::Parse(format!("record {i}: truncated body")));
        }
        out.push(PatchRecord {
            vaddr,
            flags,
            stock: blob[body..body + len].to_vec(),
            target: blob[body + len..body + len * 2].to_vec(),
        });
        off = body + len * 2;
    }
    Ok(out)
}
