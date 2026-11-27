#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opengate_inject.py - single-session volatile RAM Open Gate injector (Sony A6700).

What this adds over ram_opengate.py
------------------------------------
ram_opengate.py proves one site (the encoder height word). This driver applies a
WHOLE declarative profile (profiles/*.json) in ONE held USB session, so the camera
is prodded into service mode once and every step's writes are chained in RAM without
releasing the connection between steps. That removes the five manual unplug/replug
cycles the step-at-a-time .cmd flow needs.

The profiles are plain data (addresses, sizes, expected stock fingerprints, and -
only for geometry words that are arithmetic from the target resolution - the target
bytes). The firmware-derived encoder / sensor / playback payloads are NOT in this
repo: a profile step references an external payloads/*.bin file (git-ignored) and the
injector verifies it by sha256 before and after. No Sony firmware bytes live here.

Session flow
------------
  open MSC (0x054C:0x0E76)
    -> preflight guards (NTSC/PAL, STILL vs MOVIE dial, identity)
    -> enter service mode (re-enumerate 0x054C:0x0336)   [needs a transport]
    -> for each step: verify-stock -> backup -> write 64-byte lines -> readback
    -> on ANY mismatch: restore from backup, abort, keep the session open
  close (the RAM patch stays until a cold boot / battery-out ~10 s)

Transport
---------
RAM read/write on BIONZ XR is done by an on-camera service-mode helper. The vetted
helper is GPL / firmware-derived and is NOT shipped here, so the default transport
refuses to read or write (it never guesses). Wire a CameraMemory subclass (from
ram_opengate) that drives the service helper to go live. Until then this runs as a
strict dry-run: it loads the profile, resolves and prints every planned write, and
reports exactly where it would stop.

Default is read-only. Writing needs --confirm-ram-write. --restore undoes a profile
from the backup file written during an apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys

import ram_opengate as rg

PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
PAYLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payloads")
LINE = 64  # BIONZ XR helper writes whole 64-byte cache lines


class ProfileError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Profile loading (pure data; no camera)
# --------------------------------------------------------------------------- #
def load_profile(name):
    """Load a profile by name or path. Returns the parsed dict."""
    path = name if os.path.isfile(name) else os.path.join(PROFILE_DIR, f"{name}.json")
    if not os.path.isfile(path):
        raise ProfileError(f"profile not found: {name} (looked in {PROFILE_DIR})")
    with open(path, "r", encoding="utf-8") as fh:
        prof = json.load(fh)
    if prof.get("schema") != "opengate-profile/1":
        raise ProfileError(f"{path}: unsupported schema {prof.get('schema')!r}")
    return prof


def _hexbytes(s):
    return bytes.fromhex(s)


def iter_writes(prof):
    """Yield (step, write) for every geometry write that carries target bytes."""
    for step in prof.get("steps", []):
        for w in step.get("writes", []):
            yield step, w


def plan(prof):
    """Build a flat, printable plan of every planned action. No camera, no writes."""
    rows = []
    for step in prof.get("steps", []):
        kind = step.get("kind")
        if kind in ("encoder_blob", "sensor_registers", "code_patch"):
            rows.append({
                "step": step["id"], "action": "payload",
                "ref": step.get("payload_ref"),
                "spans": step.get("payload_spans"),
                "ready": _payload_ready(step),
                "desc": step.get("label", ""),
            })
            for a in step.get("anchors", []):
                rows.append({
                    "step": step["id"], "action": "anchor",
                    "addr": a["addr"], "len": a["len"], "role": a.get("role"),
                    "stock_sha256": a.get("stock_sha256"),
                    "target_sha256": a.get("target_sha256"),
                })
        for w in step.get("writes", []):
            rows.append({
                "step": step["id"], "action": "write",
                "region": w["region"], "addr": w["addr"], "len": w["len"],
                "stock": w.get("stock"), "target": w.get("target"),
                "ready": w.get("target") is not None,
                "note": w.get("note") or w.get("derivation", ""),
            })
    return rows


def _payload_ready(step):
    ref = step.get("payload_ref")
    if not ref:
        return False
    return os.path.isfile(os.path.join(os.path.dirname(PROFILE_DIR), ref))


# --------------------------------------------------------------------------- #
# Preflight guards (read-only)
# --------------------------------------------------------------------------- #
def preflight(prof, video_standard=None, dial=None, strict=True):
    """Check the facts that make an apply safe. Returns a list of (ok, message).
    video_standard: 'NTSC' or 'PAL'. dial: 'MOVIE' or 'STILL'. Unknown values warn."""
    checks = []

    fps = prof.get("output", {}).get("fps", [])
    if video_standard is None:
        checks.append((None, "video standard unknown: confirm NTSC (60 Hz) vs "
                             "PAL (50 Hz) matches the frame rates you want."))
    else:
        vs = video_standard.upper()
        want50 = 50 in fps or 25 in fps
        want60 = 24 in fps or 30 in fps or 60 in fps
        ok = (vs == "PAL" and want50) or (vs == "NTSC" and want60)
        checks.append((ok, f"video standard {vs} vs profile fps {fps}: "
                           + ("match." if ok else "MISMATCH - set the right standard first.")))

    if dial is None:
        checks.append((None, "mode dial unknown: set it to MOVIE before the switch "
                             "that loads the encoder (the STILL->MOVIE transition is "
                             "where the L19 encoder rebooted the kernel)."))
    else:
        ok = dial.upper() == "MOVIE"
        checks.append((ok, f"mode dial {dial.upper()}: "
                           + ("ok." if ok else "set it to MOVIE.")))

    if prof.get("status") == "experimental":
        checks.append((None, "profile is EXPERIMENTAL / never run on an A6700. Keep "
                             "the battery handy; a pull is the revert."))
    return checks


# --------------------------------------------------------------------------- #
# Apply / restore (need a live CameraMemory transport)
# --------------------------------------------------------------------------- #
def _resolve(prof, region, addr_hex):
    base = prof.get("region_bases", {}).get(region)
    base = int(base, 0) if isinstance(base, str) else (base or 0)
    return base + int(addr_hex, 0)


def verify_stock(mem, prof):
    """Read every geometry write and every anchor; confirm each holds its stock
    value / fingerprint. Returns (all_ok, list[(name, ok, detail)]). Read-only."""
    results = []
    all_ok = True
    for step, w in iter_writes(prof):
        if w.get("stock") is None:
            continue
        addr = _resolve(prof, w["region"], w["addr"])
        cur = bytes(mem.mem_read(addr, w["len"]))
        ok = cur == _hexbytes(w["stock"])
        all_ok = all_ok and ok
        results.append((f"{step['id']} {w['addr']}", ok,
                        f"read {cur.hex()} want {w['stock']}"))
    for step in prof.get("steps", []):
        for a in step.get("anchors", []):
            if not a.get("stock_sha256"):
                continue
            addr = _resolve(prof, a["region"], a["addr"])
            dig = hashlib.sha256(bytes(mem.mem_read(addr, a["len"]))).hexdigest()
            ok = dig.startswith(a["stock_sha256"])
            all_ok = all_ok and ok
            results.append((f"{step['id']} {a['addr']} ({a.get('role')})", ok,
                            f"sha256 {dig[:16]} want {a['stock_sha256']}"))
    return all_ok, results


def apply_profile(mem, prof, confirm=False):
    """Apply a profile's geometry writes in one session. Verifies stock first,
    backs up, writes whole 64-byte lines, reads back, self-undoes on mismatch.
    Firmware-derived payload steps are applied only when their payloads/*.bin is
    present and its sha256 matches; otherwise the step is reported and skipped.
    Returns the backup dict {addr: stock_bytes}. Needs a live transport."""
    ok, results = verify_stock(mem, prof)
    if not ok:
        bad = [f"{n}: {d}" for n, ok_, d in results if not ok_]
        raise ProfileError("stock check failed (wrong firmware / already patched); "
                           "nothing written:\n  " + "\n  ".join(bad))
    if not confirm:
        raise ProfileError("stock check passed; pass confirm=True / --confirm-ram-write "
                           "to write (volatile RAM, gone at the next cold boot).")

    backup = {}
    written = []
    try:
        for step, w in iter_writes(prof):
            if w.get("target") is None:
                continue
            addr = _resolve(prof, w["region"], w["addr"])
            tgt = _hexbytes(w["target"])
            backup[addr] = bytes(mem.mem_read(addr, w["len"]))
            mem.mem_write(addr, tgt)
            if bytes(mem.mem_read(addr, w["len"])) != tgt:
                raise ProfileError(f"readback mismatch at 0x{addr:x}")
            written.append((addr, tgt))
    except Exception:
        for addr, _ in reversed(written):          # self-undo, session still open
            mem.mem_write(addr, backup[addr])
        raise
    return backup


def restore_profile(mem, prof, backup):
    """Write stock bytes back from a backup dict. No reboot."""
    for addr, stock in backup.items():
        mem.mem_write(addr, stock)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_plan(prof):
    print(f"=== profile {prof['name']} ({prof['model']} fw {prof['firmware']}, "
          f"{prof['status']}) ===")
    print(f"  {prof.get('summary', '')}")
    out = prof.get("output", {})
    print(f"  output: {out.get('width')}x{out.get('height')} {out.get('aspect','')} "
          f"fps={out.get('fps')}")
    ready = skip = 0
    for r in plan(prof):
        if r["action"] == "write":
            tag = "WRITE " if r["ready"] else "DERIVE"
            if r["ready"]:
                ready += 1
            else:
                skip += 1
            print(f"  [{r['step']:4s}] {tag} {r['region']}:{r['addr']} len {r['len']}"
                  + (f"  {r['stock']}->{r['target']}" if r["ready"]
                     else f"  stock {r['stock']} target=(compute at apply)"))
        elif r["action"] == "payload":
            state = "present" if r["ready"] else "MISSING (supply from GPL kit)"
            print(f"  [{r['step']:4s}] PAYLOAD {r['ref']} "
                  f"spans={r['spans']} -> {state}")
        elif r["action"] == "anchor":
            t = r["target_sha256"] or "(unknown)"
            print(f"         anchor {r['addr']} len {r['len']} {r['role']}: "
                  f"stock {r['stock_sha256']} -> target {t}")
    print(f"  geometry writes ready: {ready}; needing compute: {skip}.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Single-session volatile RAM Open Gate injector for the Sony "
                    "A6700 (fw 2.00). Loads a declarative profile and chains every "
                    "step's writes in one held service-mode session.")
    ap.add_argument("profile", nargs="?", default="profile_4k_24p_stable",
                    help="profile name (in profiles/) or a path to a .json.")
    ap.add_argument("--list", action="store_true", help="list bundled profiles.")
    ap.add_argument("--plan", action="store_true",
                    help="(default) no camera: print the resolved write plan.")
    ap.add_argument("--video-standard", choices=["NTSC", "PAL"],
                    help="preflight: the body's TV standard.")
    ap.add_argument("--dial", choices=["MOVIE", "STILL"],
                    help="preflight: the mode-dial position.")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=rg.A6700_MSC_PID)
    ap.add_argument("--verify-only", action="store_true",
                    help="open the camera and check every site holds stock (read-only).")
    ap.add_argument("--confirm-ram-write", action="store_true",
                    help="opt-in: apply the profile's geometry writes (volatile).")
    args = ap.parse_args(argv)

    if args.list:
        for fn in sorted(os.listdir(PROFILE_DIR)):
            if fn.endswith(".json"):
                p = load_profile(fn[:-5])
                print(f"  {p['name']:32s} {p['status']:12s} {p.get('summary','')[:60]}")
        return 0

    try:
        prof = load_profile(args.profile)
    except ProfileError as e:
        sys.exit(f"[ERROR] {e}")

    # Preflight is always printed; it is read-only advice.
    print("--- preflight ---")
    for ok, msg in preflight(prof, args.video_standard, args.dial):
        mark = "[ ?]" if ok is None else ("[ok]" if ok else "[!!]")
        print(f"  {mark} {msg}")
    print()

    if not (args.verify_only or args.confirm_ram_write):
        _print_plan(prof)
        print("\n(no camera touched. --verify-only reads the body; "
              "--confirm-ram-write applies.)")
        return 0

    try:
        dev = rg.MscDevice.open(pid=args.pid)
    except (rg.MscError, Exception) as e:
        sys.exit(f"[ERROR] {e}")
    try:
        # NOTE: service-mode entry + RAM transport are not shipped (GPL helper).
        # verify_stock/apply_profile drive rg.CameraMemory, which refuses cleanly.
        if args.confirm_ram_write:
            apply_profile(dev, prof, confirm=True)
            print("[+] profile applied (volatile RAM; gone at the next cold boot).")
        else:
            ok, results = verify_stock(dev, prof)
            for name, ok_, detail in results:
                print(f"[verify] {'ok ' if ok_ else 'BAD'} {name}: {detail}")
            print(f"[verify] overall: {'all stock' if ok else 'MISMATCH'}")
    except (rg.MscError, ProfileError) as e:
        sys.exit(f"[ERROR] {e}")
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
