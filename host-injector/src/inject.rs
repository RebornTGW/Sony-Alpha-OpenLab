//! The single-session injection logic: preflight, verify, and an RAII-guarded
//! apply that rolls back already-written steps on any failure mid-chain.

use crate::descriptor::records;
use crate::profile::Profile;
use crate::transport::RamTransport;
use crate::{Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VideoStd {
    Ntsc,
    Pal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dial {
    Movie,
    Still,
}

/// One preflight line: `ok=None` is a warning, `Some(true/false)` pass/fail.
#[derive(Debug, Clone)]
pub struct PreflightItem {
    pub ok: Option<bool>,
    pub msg: String,
}

/// Read-only preflight guards run before any write.
pub fn preflight(prof: &Profile, vs: Option<VideoStd>, dial: Option<Dial>) -> Vec<PreflightItem> {
    let mut out = Vec::new();
    let fps = &prof.output.fps;

    match vs {
        None => out.push(PreflightItem {
            ok: None,
            msg: "video standard unknown: confirm NTSC (60 Hz) vs PAL (50 Hz) matches \
                  the frame rates you want."
                .into(),
        }),
        Some(v) => {
            let want50 = fps.contains(&50) || fps.contains(&25);
            let want60 = fps.contains(&24) || fps.contains(&30) || fps.contains(&60);
            let ok = (v == VideoStd::Pal && want50) || (v == VideoStd::Ntsc && want60);
            out.push(PreflightItem {
                ok: Some(ok),
                msg: format!("video standard {v:?} vs profile fps {fps:?}: {}", if ok { "match." } else { "MISMATCH." }),
            });
        }
    }

    match dial {
        None => out.push(PreflightItem {
            ok: None,
            msg: "mode dial unknown: set it to MOVIE before the switch that loads the \
                  encoder (the STILL->MOVIE transition is where L19 rebooted the kernel)."
                .into(),
        }),
        Some(d) => {
            let ok = d == Dial::Movie;
            out.push(PreflightItem {
                ok: Some(ok),
                msg: format!("mode dial {d:?}: {}", if ok { "ok." } else { "set it to MOVIE." }),
            });
        }
    }

    if prof.status == "experimental" {
        out.push(PreflightItem {
            ok: None,
            msg: "profile is EXPERIMENTAL / never run on an A6700. Keep the battery \
                  handy; a pull is the revert."
                .into(),
        });
    }
    out
}

/// A printable plan line (no camera).
#[derive(Debug, Clone)]
pub struct PlanLine {
    pub step: String,
    pub region: String,
    pub addr: String,
    pub len: u32,
    pub ready: bool,
}

pub fn plan(prof: &Profile) -> Vec<PlanLine> {
    let mut v = Vec::new();
    for step in &prof.steps {
        for w in &step.writes {
            v.push(PlanLine {
                step: step.id.clone(),
                region: w.region.clone(),
                addr: w.addr.clone(),
                len: w.len,
                ready: w.target.is_some(),
            });
        }
    }
    v
}

/// Read every geometry write that has a stock value and confirm RAM holds it.
/// Returns Err(Stock) on the first mismatch (nothing is written here).
pub fn verify_stock<T: RamTransport>(prof: &Profile, t: &mut T) -> Result<()> {
    for step in &prof.steps {
        for w in &step.writes {
            if let Some(stock) = w.stock_bytes()? {
                let addr = prof.resolve(w)?;
                let cur = t.read(addr, stock.len())?;
                if cur != stock {
                    return Err(Error::Stock(format!(
                        "{} @0x{addr:x}: read {} want {}",
                        step.id,
                        hex(&cur),
                        hex(&stock)
                    )));
                }
            }
        }
    }
    Ok(())
}

/// RAII session guard: each `write` is verified + backed up; on drop without
/// `commit()`, every write done so far is undone in reverse order — the rollback
/// the task asks for, fired automatically on an error path.
struct SessionGuard<'a, T: RamTransport> {
    t: &'a mut T,
    done: Vec<(u64, Vec<u8>)>,
    committed: bool,
}

impl<'a, T: RamTransport> SessionGuard<'a, T> {
    fn new(t: &'a mut T) -> Self {
        Self { t, done: Vec::new(), committed: false }
    }

    fn write(&mut self, addr: u64, target: &[u8]) -> Result<()> {
        let stock = self.t.read(addr, target.len())?;
        self.t.write(addr, target)?;
        let rb = self.t.read(addr, target.len())?;
        if rb != target {
            // undo just this one, then fail (the Drop undoes the earlier ones)
            let _ = self.t.write(addr, &stock);
            return Err(Error::Readback(format!(
                "@0x{addr:x}: read {} want {}",
                hex(&rb),
                hex(target)
            )));
        }
        self.done.push((addr, stock));
        Ok(())
    }

    fn commit(&mut self) {
        self.committed = true;
    }
}

impl<'a, T: RamTransport> Drop for SessionGuard<'a, T> {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        for (addr, stock) in self.done.iter().rev() {
            let _ = self.t.write(*addr, stock);
        }
    }
}

/// Apply a profile's geometry writes in one session. Refuses outright if the
/// profile resolves to zero writes (e.g. a locked multi-camera skeleton whose
/// steps are all still `"writes": []`, pending `--dump-ram` / `--scan-dump`) -
/// no point opening the camera and verifying stock for a no-op. Otherwise
/// verifies all stock first, then writes with per-step readback; any failure
/// rolls the whole chain back via the RAII guard. Firmware-derived payload steps
/// are not applied here (no bytes).
pub fn apply_profile<T: RamTransport>(prof: &Profile, t: &mut T) -> Result<usize> {
    let recs = records(prof)?;
    if recs.is_empty() {
        return Err(Error::Parse(format!(
            "{} has zero resolved writes (every step's \"writes\" is empty, or none carry \
             both stock and target bytes yet) - nothing to apply. Use --dump-ram to read \
             candidate offsets off the body and --scan-dump to locate them from a target \
             firmware dump against a verified reference profile, then fill in this \
             profile's writes before trying --confirm-ram-write.",
            prof.name
        )));
    }
    verify_stock(prof, t)?;
    let mut guard = SessionGuard::new(t);
    for r in &recs {
        guard.write(r.vaddr, &r.target)?; // early-return here triggers rollback on drop
    }
    guard.commit();
    Ok(recs.len())
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

// --------------------------------------------------------------------------- //
#[cfg(test)]
mod tests {
    use super::*;
    use crate::descriptor::{build_blob, parse_blob, records};
    use crate::transport::{MockRam, NullTransport};
    use std::path::PathBuf;

    fn profiles_dir() -> PathBuf {
        // crate is at host-injector/; profiles live at ../profiles/
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../profiles")
    }

    fn load(name: &str) -> Profile {
        Profile::load(&profiles_dir(), name).expect("profile loads")
    }

    fn seed_stock(prof: &Profile, ram: &mut MockRam) {
        for step in &prof.steps {
            for w in &step.writes {
                if let Some(s) = w.stock_bytes().unwrap() {
                    ram.seed(prof.resolve(w).unwrap(), &s);
                }
            }
        }
    }

    #[test]
    fn all_profiles_load() {
        for n in ["profile_4k_24p_stable", "profile_true_3x2_experimental", "playback_fix"] {
            let p = load(n);
            assert_eq!(p.schema, "opengate-profile/1");
        }
    }

    #[test]
    fn stable_height_word_is_2560() {
        let p = load("profile_4k_24p_stable");
        let w = p
            .steps
            .iter()
            .flat_map(|s| &s.writes)
            .find(|w| w.addr == "0x0199ecc4")
            .expect("output-size write present");
        let t = w.target_bytes().unwrap().unwrap();
        let word = u32::from_le_bytes([t[0], t[1], t[2], t[3]]);
        assert_eq!(word & 0xFFFF, 0x0F00); // width 3840
        assert_eq!((word >> 16) & 0xFFFF, 0x0A00); // height 2560
    }

    #[test]
    fn descriptor_roundtrips() {
        let p = load("profile_4k_24p_stable");
        let recs = records(&p).unwrap();
        assert!(!recs.is_empty());
        let blob = build_blob(&recs);
        assert_eq!(&blob[0..4], b"OGP1");
        assert_eq!(parse_blob(&blob).unwrap(), recs);
    }

    #[test]
    fn experimental_has_deferred_targets() {
        // true-3:2 L13 buffer writes have stock but no target yet -> not encoded.
        let p = load("profile_true_3x2_experimental");
        let recs = records(&p).unwrap();
        // only the output-size + screen geometry carry targets; buffer rows do not.
        assert!(recs.iter().all(|r| !r.target.is_empty()));
        let total_writes: usize = p.steps.iter().map(|s| s.writes.len()).sum();
        assert!(recs.len() < total_writes);
    }

    #[test]
    fn verify_stock_passes_when_seeded() {
        let p = load("profile_4k_24p_stable");
        let mut ram = MockRam::new();
        seed_stock(&p, &mut ram);
        verify_stock(&p, &mut ram).expect("stock matches");
    }

    #[test]
    fn apply_then_ram_holds_targets() {
        let p = load("profile_4k_24p_stable");
        let mut ram = MockRam::new();
        seed_stock(&p, &mut ram);
        let n = apply_profile(&p, &mut ram).expect("apply ok");
        assert_eq!(n, records(&p).unwrap().len());
        for r in records(&p).unwrap() {
            assert_eq!(ram.read(r.vaddr, r.target.len()).unwrap(), r.target);
        }
    }

    #[test]
    fn rollback_restores_stock_on_readback_failure() {
        let p = load("profile_4k_24p_stable");
        let recs = records(&p).unwrap();
        assert!(recs.len() >= 2);
        let mut ram = MockRam::new();
        seed_stock(&p, &mut ram);
        // Make the LAST record's write silently fail -> readback diverges.
        ram.bad_addr = Some(recs.last().unwrap().vaddr);

        let err = apply_profile(&p, &mut ram);
        assert!(matches!(err, Err(Error::Readback(_))));
        // Every site is back to its stock bytes (full chain rolled back).
        for r in &recs {
            let stock_matches = ram.read(r.vaddr, r.stock.len()).unwrap() == r.stock;
            assert!(stock_matches, "site 0x{:x} not restored", r.vaddr);
        }
    }

    #[test]
    fn apply_profile_refuses_zero_resolved_writes() {
        // Shaped like the locked multi-camera skeletons (profiles/fx30_v5.00.json
        // and friends): a real step id, but "writes": [] - pending --dump-ram /
        // --scan-dump. No camera touched here (MockRam would happily no-op), so
        // this specifically checks apply_profile() refuses before even trying.
        let p = Profile {
            schema: "opengate-profile/1".into(),
            name: "skeleton_test".into(),
            status: "experimental".into(),
            output: Default::default(),
            region_bases: Default::default(),
            steps: vec![crate::profile::Step {
                id: "L13".into(),
                label: String::new(),
                kind: "geometry".into(),
                writes: vec![],
            }],
            summary: String::new(),
        };
        let mut ram = MockRam::new();
        let err = apply_profile(&p, &mut ram).unwrap_err();
        assert!(matches!(err, Error::Parse(ref s) if s.contains("zero resolved writes")));
        assert!(matches!(err, Error::Parse(ref s) if s.contains("--dump-ram") && s.contains("--scan-dump")));
    }

    #[test]
    fn null_transport_refuses() {
        let p = load("profile_4k_24p_stable");
        let mut t = NullTransport;
        assert!(matches!(verify_stock(&p, &mut t), Err(Error::NoTransport)));
    }

    #[test]
    fn preflight_flags_still_dial() {
        let p = load("profile_4k_24p_stable");
        let items = preflight(&p, Some(VideoStd::Ntsc), Some(Dial::Still));
        assert!(items.iter().any(|i| i.ok == Some(false)));
    }
}
