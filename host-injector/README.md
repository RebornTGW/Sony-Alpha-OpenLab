# host-injector — `opengate-rs` (Rust, clean-room MIT)

The host side of the single-session RAM Open Gate injector. Loads the repo's
[`../profiles/*.json`](../profiles/) directly, builds the **OGP1** patch blob the
on-camera helper ([`../target-helper`](../target-helper)) applies, and drives a
one-session USB state machine with automatic rollback.

## What it does

- **Load profiles** — `serde_json` over the existing JSON (unknown fields ignored, so
  it tracks the richer files without duplicating them).
- **USB state machine** — detect Mass Storage `054C:0E76` → switch to service mode
  `054C:0336` → preflight (NTSC/PAL vs the profile's fps, STILL/MOVIE dial) → chain
  every step's writes in RAM, connection held the whole time.
- **RAII rollback** — a `SessionGuard` records each write's stock bytes; if any write
  fails its readback (or a USB error fires mid-chain), `Drop` undoes every write done
  so far, in reverse. No half-applied state left behind.
- **Refuses to guess** — the service-mode handshake and RAM read/write live in the
  on-camera helper, not shipped here, so the USB transport returns `NoTransport`
  until wired. `MockRam` stands in for the tests.

## Build & test

```bash
cd host-injector
cargo check          # type-check
cargo test           # unit tests (profile load, descriptor round-trip, rollback)
cargo run -- --list                                   # list profiles (no camera)
cargo run -- profile_4k_24p_stable --video-standard NTSC --dial MOVIE   # plan + preflight
```

> Needs the camera only for `--verify-only` / `--confirm-ram-write`; everything else
> (plan, preflight, tests) runs with no hardware.

## Vendor protocol (`pmca.rs`)

The Sony USB vendor framing (MSC vendor CDB `0x7a`, `ExtCmdHeader`, Senser service
mode + FileControl/MemoryDump, the service PIDs) is transcribed **clean-room** from
the public MIT project [`ma1co/Sony-PMCA-RE`](https://github.com/ma1co/Sony-PMCA-RE),
cited by file + symbol in the source. Two pieces are **gaps** not in the fetched
files — the Senser auth keys and the camera-shell exec tokens (both under
`pmca/platform`) — so the end-to-end path cannot complete from public MIT alone, and
those steps refuse rather than guess.

Two gates protect the camera:
- `VENDOR_PROTOCOL_VERIFIED` (compile-time) stays `false` until proven on a real A6700.
- `--allow-unverified-usb` (runtime, with an interactive `yes` confirm) lets a tester
  send real frames without recompiling. Even then the documented gaps still refuse.

## Clean-room / safety

No Sony firmware bytes. Geometry words are arithmetic from the target resolution and
come straight from the JSON; firmware-derived payloads stay in git-ignored
`payloads/`. Default is a no-camera plan. Writing needs `--confirm-ram-write`, is
RAM-only, and reverts on a cold boot (battery out ~10 s).
