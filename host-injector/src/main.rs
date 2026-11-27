//! opengate-rs CLI — load a profile, print preflight + plan, and (opt-in) drive the
//! single-session injector. Default is no-camera `--plan`. Minimal hand-rolled arg
//! parsing to keep the dependency surface small.

use std::path::PathBuf;
use std::process::ExitCode;

use opengate_rs::inject::{apply_profile, plan, preflight, verify_stock, Dial, VideoStd};
use opengate_rs::profile::Profile;
use opengate_rs::usb::open_a6700;

fn usage() {
    eprintln!(
        "opengate-rs - single-session RAM Open Gate injector (A6700, host side)\n\
\n\
USAGE:\n\
  opengate-rs [PROFILE] [options]\n\
\n\
  PROFILE                 profile name in profiles/ (default: profile_4k_24p_stable)\n\
                          or a path to a .json\n\
OPTIONS:\n\
  --list                  list bundled profiles\n\
  --plan                  (default) print the resolved write plan, no camera\n\
  --verify-only           open the camera and confirm every site holds stock\n\
  --confirm-ram-write     opt-in: apply the profile (volatile RAM)\n\
  --video-standard NTSC|PAL   preflight: body TV standard\n\
  --dial MOVIE|STILL          preflight: mode-dial position\n\
  --profiles-dir DIR      where to find the JSON profiles (default: ../profiles)\n"
    );
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let mut profile_name = String::from("profile_4k_24p_stable");
    let mut profiles_dir = PathBuf::from("../profiles");
    let mut do_list = false;
    let mut verify_only = false;
    let mut confirm = false;
    let mut vs: Option<VideoStd> = None;
    let mut dial: Option<Dial> = None;

    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-h" | "--help" => {
                usage();
                return ExitCode::SUCCESS;
            }
            "--list" => do_list = true,
            "--plan" => {}
            "--verify-only" => verify_only = true,
            "--confirm-ram-write" => confirm = true,
            "--video-standard" => {
                vs = match it.next().map(|s| s.to_ascii_uppercase()).as_deref() {
                    Some("NTSC") => Some(VideoStd::Ntsc),
                    Some("PAL") => Some(VideoStd::Pal),
                    other => {
                        eprintln!("bad --video-standard {other:?}");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--dial" => {
                dial = match it.next().map(|s| s.to_ascii_uppercase()).as_deref() {
                    Some("MOVIE") => Some(Dial::Movie),
                    Some("STILL") => Some(Dial::Still),
                    other => {
                        eprintln!("bad --dial {other:?}");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--profiles-dir" => {
                if let Some(d) = it.next() {
                    profiles_dir = PathBuf::from(d);
                }
            }
            s if !s.starts_with('-') => profile_name = s.to_string(),
            s => {
                eprintln!("unknown option {s:?}");
                usage();
                return ExitCode::FAILURE;
            }
        }
    }

    if do_list {
        return match list_profiles(&profiles_dir) {
            Ok(()) => ExitCode::SUCCESS,
            Err(e) => {
                eprintln!("[ERROR] {e}");
                ExitCode::FAILURE
            }
        };
    }

    let prof = match Profile::load(&profiles_dir, &profile_name) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("[ERROR] {e}");
            return ExitCode::FAILURE;
        }
    };

    println!("--- preflight ---");
    for item in preflight(&prof, vs, dial) {
        let mark = match item.ok {
            None => "[ ?]",
            Some(true) => "[ok]",
            Some(false) => "[!!]",
        };
        println!("  {mark} {}", item.msg);
    }
    println!();

    if !verify_only && !confirm {
        print_plan(&prof);
        println!("\n(no camera touched. --verify-only reads the body; --confirm-ram-write applies.)");
        return ExitCode::SUCCESS;
    }

    // Camera path: open MSC -> probe (read-only) -> service mode -> verify / apply,
    // all on one held session.
    let mut link = match open_a6700() {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[ERROR] {e}");
            return ExitCode::FAILURE;
        }
    };
    if let Err(e) = link.probe() {
        eprintln!("[ERROR] probe: {e}");
        return ExitCode::FAILURE;
    }
    if let Err(e) = link.enter_service() {
        eprintln!("[ERROR] {e}");
        return ExitCode::FAILURE;
    }

    // A write chain needs the on-camera helper loaded first.
    if confirm {
        match find_helper_so() {
            Some(path) => match std::fs::read(&path) {
                Ok(bytes) => {
                    if let Err(e) = link.upload_helper(&bytes) {
                        eprintln!("[ERROR] upload helper: {e}");
                        return ExitCode::FAILURE;
                    }
                    println!("[+] uploaded helper {} ({} bytes)", path.display(), bytes.len());
                }
                Err(e) => {
                    eprintln!("[ERROR] read {}: {e}", path.display());
                    return ExitCode::FAILURE;
                }
            },
            None => {
                eprintln!(
                    "[ERROR] libogpatch.so not found. Build it: cd ../target-helper && zig build"
                );
                return ExitCode::FAILURE;
            }
        }
    }

    let res = if confirm {
        apply_profile(&prof, &mut link).map(|n| println!("[+] applied {n} writes (volatile)."))
    } else {
        verify_stock(&prof, &mut link).map(|_| println!("[verify] all sites stock."))
    };
    match res {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("[ERROR] {e}");
            ExitCode::FAILURE
        }
    }
}

/// Look for the compiled aarch64 helper in the usual build output locations.
fn find_helper_so() -> Option<PathBuf> {
    let candidates = [
        "../target-helper/zig-out/lib/libogpatch.so",
        "../target-helper/build/libogpatch.so",
        "target-helper/zig-out/lib/libogpatch.so",
    ];
    candidates.iter().map(PathBuf::from).find(|p| p.is_file())
}

fn list_profiles(dir: &std::path::Path) -> opengate_rs::Result<()> {
    let mut names: Vec<_> = std::fs::read_dir(dir)
        .map_err(|e| opengate_rs::Error::Io(format!("{}: {e}", dir.display())))?
        .filter_map(|e| e.ok())
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| n.ends_with(".json"))
        .collect();
    names.sort();
    for n in names {
        let stem = n.trim_end_matches(".json");
        if let Ok(p) = Profile::load(dir, stem) {
            let s: String = p.summary.chars().take(60).collect();
            println!("  {:32} {:12} {}", p.name, p.status, s);
        }
    }
    Ok(())
}

fn print_plan(prof: &Profile) {
    println!(
        "=== profile {} ({}, {}) ===",
        prof.name, prof.output.aspect, prof.status
    );
    println!("  {}", prof.summary);
    let mut ready = 0usize;
    let mut deferred = 0usize;
    for l in plan(prof) {
        if l.ready {
            ready += 1;
            println!("  [{:4}] WRITE  {}:{} len {}", l.step, l.region, l.addr, l.len);
        } else {
            deferred += 1;
            println!(
                "  [{:4}] DEFER  {}:{} len {} (target computed at apply)",
                l.step, l.region, l.addr, l.len
            );
        }
    }
    println!("  geometry writes ready: {ready}; deferred: {deferred}.");
}
