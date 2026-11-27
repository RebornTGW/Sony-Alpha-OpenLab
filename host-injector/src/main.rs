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
  --profiles-dir DIR      where to find the JSON profiles (default: ../profiles)\n\
  --allow-unverified-usb  send real (unverified) vendor frames; asks to confirm\n\
  --senser-config PATH    Senser key tables, JSON {{\"sha1\":[...],\"sha256\":[...]}}\n\
                          (3 hex strings each); also read from OG_SENSER_CONFIG\n\
  --dump-ram ADDR LEN --out PATH   opt-in: dump LEN bytes from ADDR to PATH\n\
                          (hex, e.g. 0x02580cd8 0x40; same gates as --verify-only)\n\
  --scan-dump BIN --ref-profile JSON [--out PATH]\n\
                          offline, no camera: search BIN for JSON's stock-byte\n\
                          signatures (default steps: L13, L16, S16), print (and\n\
                          optionally save) a draft experimental profile\n"
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
    let mut allow_unverified = false;
    let mut senser_config: Option<PathBuf> = None;
    let mut dump_ram: Option<(u64, usize)> = None;
    let mut out_path: Option<PathBuf> = None;
    let mut scan_dump_path: Option<PathBuf> = None;
    let mut ref_profile_path: Option<PathBuf> = None;

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
            "--allow-unverified-usb" => allow_unverified = true,
            "--senser-config" => {
                senser_config = match it.next() {
                    Some(p) => Some(PathBuf::from(p)),
                    None => {
                        eprintln!("--senser-config needs a path");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--dump-ram" => {
                let addr = it.next().map(|s| opengate_rs::parse_u64(s));
                let len = it.next().map(|s| opengate_rs::parse_u64(s));
                match (addr, len) {
                    (Some(Ok(a)), Some(Ok(l))) => dump_ram = Some((a, l as usize)),
                    _ => {
                        eprintln!("--dump-ram needs HEX_ADDR HEX_LEN (e.g. 0x4010 0x40)");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--out" => {
                out_path = match it.next() {
                    Some(p) => Some(PathBuf::from(p)),
                    None => {
                        eprintln!("--out needs a path");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--scan-dump" => {
                scan_dump_path = match it.next() {
                    Some(p) => Some(PathBuf::from(p)),
                    None => {
                        eprintln!("--scan-dump needs a path");
                        return ExitCode::FAILURE;
                    }
                }
            }
            "--ref-profile" => {
                ref_profile_path = match it.next() {
                    Some(p) => Some(PathBuf::from(p)),
                    None => {
                        eprintln!("--ref-profile needs a path");
                        return ExitCode::FAILURE;
                    }
                }
            }
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

    // Offline mode: no camera, no profile positional arg - just two local files.
    if let Some(dump_path) = &scan_dump_path {
        let ref_path = match &ref_profile_path {
            Some(p) => p,
            None => {
                eprintln!("--scan-dump needs --ref-profile <JSON_PATH>");
                return ExitCode::FAILURE;
            }
        };
        return run_scan_dump(dump_path, ref_path, out_path.as_deref());
    }
    if ref_profile_path.is_some() {
        eprintln!("--ref-profile needs --scan-dump <BIN_PATH>");
        return ExitCode::FAILURE;
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

    if !verify_only && !confirm && dump_ram.is_none() {
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

    if allow_unverified {
        if !confirm_unverified() {
            eprintln!("[abort] --allow-unverified-usb not confirmed.");
            return ExitCode::FAILURE;
        }
        link.set_allow_unverified(true);
        println!("[warn ] unverified USB vendor frames ENABLED for this run.");
    }

    let senser_config = senser_config.or_else(|| std::env::var("OG_SENSER_CONFIG").ok().map(PathBuf::from));
    if let Some(path) = &senser_config {
        match opengate_rs::pmca::load_senser_keys_json(path) {
            Ok(keys) => match link.set_senser_keys(keys) {
                Ok(()) => println!("[+] loaded senser key tables from {}", path.display()),
                Err(e) => {
                    eprintln!("[ERROR] senser keys: {e}");
                    return ExitCode::FAILURE;
                }
            },
            Err(e) => {
                eprintln!("[ERROR] senser config {}: {e}", path.display());
                return ExitCode::FAILURE;
            }
        }
    }

    // Senser re-enumeration lifecycle: StartSenser rides the still-open MSC
    // handle, then the camera is expected to drop off the bus and come back as
    // 054C:0336. Gated on --allow-unverified-usb like every other real frame;
    // the confirm above already covered this run.
    if allow_unverified {
        println!("[senser] sending StartSenser on the MSC handle...");
        if let Err(e) = link.send_vendor_control(opengate_rs::pmca::vendor::VREQ_START_SENSER) {
            eprintln!("[ERROR] StartSenser: {e}");
            return ExitCode::FAILURE;
        }
        link.release_pipe();

        println!("[senser] waiting for the camera to re-enumerate as 054C:0336 (up to 10s)...");
        if !wait_for_pid(
            opengate_rs::usb::SONY_VID,
            0x0336,
            std::time::Duration::from_secs(10),
            std::time::Duration::from_millis(200),
        ) {
            eprintln!("[ERROR] camera did not re-enumerate as 054C:0336 within 10s");
            return ExitCode::FAILURE;
        }

        let senser_io = match opengate_rs::pmca::RusbSenserIo::open(opengate_rs::usb::SONY_VID, 0x0336) {
            Ok(io) => io,
            Err(e) => {
                eprintln!("[ERROR] opening senser device: {e}");
                return ExitCode::FAILURE;
            }
        };
        link.set_senser_io(Box::new(senser_io));
        println!("[+] senser transport wired (054C:0336).");
    }

    if let Err(e) = link.enter_service() {
        eprintln!("[ERROR] {e}");
        return ExitCode::FAILURE;
    }

    // Standalone read: dumps straight from the held service-mode session, chunked
    // through ramdump::dump_ram (each chunk's RMEM frame built by
    // pmca::mem_read_request under ServiceLink::read). Independent of --verify-only
    // / --confirm-ram-write - returns here rather than falling into the apply path.
    if let Some((addr, len)) = dump_ram {
        let out_path = match &out_path {
            Some(p) => p.clone(),
            None => {
                eprintln!("[ERROR] --dump-ram needs --out <PATH>");
                return ExitCode::FAILURE;
            }
        };
        let chunk = opengate_rs::pmca::vendor::SENSER_CHUNK;
        println!("[dump ] reading {len:#x} bytes from {addr:#x} in {chunk:#x}-byte chunks...");
        return match opengate_rs::ramdump::dump_ram(&mut link, addr, len, chunk) {
            Ok(bytes) => match std::fs::write(&out_path, &bytes) {
                Ok(()) => {
                    println!("[+] wrote {} bytes to {}", bytes.len(), out_path.display());
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("[ERROR] write {}: {e}", out_path.display());
                    ExitCode::FAILURE
                }
            },
            Err(e) => {
                eprintln!("[ERROR] dump-ram: {e}");
                ExitCode::FAILURE
            }
        };
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

/// Interactive confirm for --allow-unverified-usb: real vendor bytes to the camera.
fn confirm_unverified() -> bool {
    use std::io::Write;
    print!(
        "\n!! --allow-unverified-usb: this sends REAL, unverified Sony vendor frames \
         to the camera.\n   Never run on an A6700; a wrong frame can reboot or wedge \
         the body (battery pull to recover).\n   Type 'yes' to proceed: "
    );
    let _ = std::io::stdout().flush();
    let mut line = String::new();
    match std::io::stdin().read_line(&mut line) {
        Ok(_) => line.trim().eq_ignore_ascii_case("yes"),
        Err(_) => false,
    }
}

/// Poll the USB device list for a VID/PID until it shows up or `timeout` elapses.
/// Used after StartSenser to wait for the camera's re-enumeration as 054C:0336.
fn wait_for_pid(vid: u16, pid: u16, timeout: std::time::Duration, interval: std::time::Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    loop {
        let found = rusb::devices().ok().is_some_and(|list| {
            list.iter()
                .any(|d| d.device_descriptor().is_ok_and(|desc| desc.vendor_id() == vid && desc.product_id() == pid))
        });
        if found {
            return true;
        }
        if std::time::Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(interval);
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

/// Offline signature scan: search `dump_path` for `ref_path`'s geometry-step stock
/// bytes, print the resulting draft profile (and save it too, if `out` is given).
/// No camera, no profile positional arg - just these two local files.
fn run_scan_dump(dump_path: &std::path::Path, ref_path: &std::path::Path, out: Option<&std::path::Path>) -> ExitCode {
    // Profile::load takes a direct file path straight through when it exists, so
    // the `dir` argument here is unused.
    let ref_prof = match Profile::load(std::path::Path::new("."), &ref_path.display().to_string()) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("[ERROR] --ref-profile {}: {e}", ref_path.display());
            return ExitCode::FAILURE;
        }
    };
    let dump = match std::fs::read(dump_path) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("[ERROR] --scan-dump {}: {e}", dump_path.display());
            return ExitCode::FAILURE;
        }
    };
    let matches = match opengate_rs::scan::scan_steps(&ref_prof, &dump, opengate_rs::scan::DEFAULT_STEP_IDS) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("[ERROR] scan: {e}");
            return ExitCode::FAILURE;
        }
    };
    let draft = opengate_rs::scan::draft_profile(&format!("{}_scan_draft", ref_prof.name), &matches);
    let pretty = serde_json::to_string_pretty(&draft).expect("draft profile serializes");
    println!("{pretty}");

    if let Some(out_path) = out {
        if let Err(e) = std::fs::write(out_path, &pretty) {
            eprintln!("[ERROR] write {}: {e}", out_path.display());
            return ExitCode::FAILURE;
        }
        eprintln!("[+] wrote draft profile to {}", out_path.display());
    }
    ExitCode::SUCCESS
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
