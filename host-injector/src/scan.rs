//! Offline firmware-dump signature scanning.
//!
//! Takes a verified reference profile's geometry writes (their literal `stock`
//! hex - already committed, "safe to ship: computed numbers, not copied firmware"
//! per `profiles/README.md`) as byte signatures, and locates matching offsets in a
//! target firmware dump the caller supplies locally. Emits a draft profile with
//! the found offsets - always `"status": "experimental"`, never auto-applied.
//! Pure byte matching over two local files; this module never fetches, embeds, or
//! ships firmware bytes of its own.

use serde_json::{json, Value};

use crate::profile::Profile;
use crate::Result;

/// The steps this scan looks at by default: the stable profile's pure-geometry
/// steps (literal `stock`/`target` hex, no firmware-derived payload).
pub const DEFAULT_STEP_IDS: &[&str] = &["L13", "L16", "S16"];

/// One write's scan result: its signature (the reference profile's `stock` bytes)
/// and every offset it was found at in the target dump (0, 1, or many).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WriteMatch {
    pub step_id: String,
    pub region: String,
    pub len: u32,
    pub signature: Vec<u8>,
    pub offsets: Vec<u64>,
}

/// Every offset where `needle` occurs in `haystack`. Naive scan - these dumps and
/// signatures are small enough (profile writes are a handful of bytes each) that
/// this stays fast and simple; no need for a Boyer-Moore/memmem dependency.
pub fn find_all(haystack: &[u8], needle: &[u8]) -> Vec<u64> {
    if needle.is_empty() || needle.len() > haystack.len() {
        return Vec::new();
    }
    (0..=(haystack.len() - needle.len()))
        .filter(|&i| haystack[i..i + needle.len()] == *needle)
        .map(|i| i as u64)
        .collect()
}

/// Scan `dump` for the stock-byte signature of every write in the reference
/// profile's `step_ids` steps. Writes with no literal `stock` hex (firmware-derived
/// payload steps, which carry only `sha256` fingerprints) are skipped - there is
/// nothing to search for without the actual bytes.
pub fn scan_steps(prof: &Profile, dump: &[u8], step_ids: &[&str]) -> Result<Vec<WriteMatch>> {
    let mut out = Vec::new();
    for step in &prof.steps {
        if !step_ids.contains(&step.id.as_str()) {
            continue;
        }
        for w in &step.writes {
            let sig = match w.stock_bytes()? {
                Some(s) if !s.is_empty() => s,
                _ => continue,
            };
            let offsets = find_all(dump, &sig);
            out.push(WriteMatch { step_id: step.id.clone(), region: w.region.clone(), len: w.len, signature: sig, offsets });
        }
    }
    Ok(out)
}

/// Build a draft `opengate-profile/1` JSON from scan results: a unique match
/// becomes a write at the found offset; an ambiguous (>1) or missing (0) match is
/// left out of `steps` and flagged in `notes` instead of guessed. Always
/// `"status": "experimental"`.
pub fn draft_profile(name: &str, matches: &[WriteMatch]) -> Value {
    let mut notes = Vec::new();
    let mut steps_by_id: std::collections::BTreeMap<&str, Vec<Value>> = std::collections::BTreeMap::new();

    for m in matches {
        let sig_hex = hex(&m.signature);
        match m.offsets.as_slice() {
            [one] => {
                steps_by_id.entry(m.step_id.as_str()).or_default().push(json!({
                    "region": m.region,
                    "addr": format!("0x{one:08x}"),
                    "len": m.len,
                    "stock": sig_hex,
                }));
            }
            [] => notes.push(format!(
                "{} (signature {sig_hex}, {} bytes): not found in the target dump - \
                 missing, or this dump covers a different region/version.",
                m.step_id, m.len
            )),
            many => notes.push(format!(
                "{} (signature {sig_hex}, {} bytes): {} candidate offsets, pick one by \
                 hand: {}",
                m.step_id,
                m.len,
                many.len(),
                many.iter().map(|o| format!("0x{o:08x}")).collect::<Vec<_>>().join(", "),
            )),
        }
    }

    let steps: Vec<Value> =
        steps_by_id.into_iter().map(|(id, writes)| json!({ "id": id, "kind": "geometry", "writes": writes })).collect();

    json!({
        "schema": "opengate-profile/1",
        "name": name,
        "status": "experimental",
        "summary": "Draft profile from offline signature scanning against a target firmware \
                    dump - NOT verified on hardware. Candidate offsets only: read back and \
                    confirm stock before trusting or applying any write.",
        "steps": steps,
        "notes": notes,
    })
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn profiles_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../profiles")
    }

    fn stable_profile() -> Profile {
        Profile::load(&profiles_dir(), "profile_4k_24p_stable").expect("profile loads")
    }

    #[test]
    fn find_all_locates_every_occurrence() {
        let hay = [0x00, 0xAA, 0xBB, 0x00, 0xAA, 0xBB, 0xFF];
        assert_eq!(find_all(&hay, &[0xAA, 0xBB]), vec![1, 4]);
    }

    #[test]
    fn find_all_empty_needle_or_too_long_is_no_match() {
        let hay = [0x11, 0x22, 0x33];
        assert_eq!(find_all(&hay, &[]), Vec::<u64>::new());
        assert_eq!(find_all(&hay, &[0x11, 0x22, 0x33, 0x44]), Vec::<u64>::new());
    }

    #[test]
    fn find_all_no_match_is_empty() {
        let hay = [0x11, 0x22, 0x33];
        assert_eq!(find_all(&hay, &[0x99]), Vec::<u64>::new());
    }

    #[test]
    fn scan_steps_only_looks_at_requested_ids_with_literal_stock() {
        let prof = stable_profile();
        // Build a dump that contains exactly one copy of the L16 stock word
        // (0x000f7008, LE) at a known offset, nothing else matching.
        let mut dump = vec![0u8; 0x100];
        dump[0x40..0x44].copy_from_slice(&[0x00, 0x0f, 0x70, 0x08]);

        let matches = scan_steps(&prof, &dump, &["L16"]).unwrap();
        assert_eq!(matches.len(), 1);
        assert_eq!(matches[0].step_id, "L16");
        assert_eq!(matches[0].offsets, vec![0x40]);

        // M19 is firmware-derived (sha256 only, no literal stock) - must be skipped
        // even if explicitly requested.
        let matches_m19 = scan_steps(&prof, &dump, &["M19"]).unwrap();
        assert!(matches_m19.is_empty());
    }

    #[test]
    fn draft_profile_unique_match_becomes_a_write_ambiguous_and_missing_become_notes() {
        let matches = vec![
            WriteMatch {
                step_id: "L16".into(),
                region: "coprocessor".into(),
                len: 4,
                signature: vec![0x00, 0x0f, 0x70, 0x08],
                offsets: vec![0x1234],
            },
            WriteMatch {
                step_id: "L13".into(),
                region: "coprocessor".into(),
                len: 4,
                signature: vec![0x00, 0x12, 0x34, 0x01],
                offsets: vec![0x10, 0x20],
            },
            WriteMatch {
                step_id: "S16".into(),
                region: "coprocessor".into(),
                len: 4,
                signature: vec![0x03, 0x00, 0x00, 0x00],
                offsets: vec![],
            },
        ];
        let draft = draft_profile("draft_test", &matches);
        assert_eq!(draft["status"], "experimental");
        let steps = draft["steps"].as_array().unwrap();
        assert_eq!(steps.len(), 1); // only L16 (the unique match) becomes a step
        assert_eq!(steps[0]["id"], "L16");
        assert_eq!(steps[0]["writes"][0]["addr"], "0x00001234");

        let notes: Vec<String> = draft["notes"].as_array().unwrap().iter().map(|n| n.as_str().unwrap().to_string()).collect();
        assert!(notes.iter().any(|n| n.starts_with("L13") && n.contains("candidate offsets")));
        assert!(notes.iter().any(|n| n.starts_with("S16") && n.contains("not found")));
    }
}
