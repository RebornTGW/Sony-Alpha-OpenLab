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
- **Refuses to guess** — the service-mode auth handshake (`enter_service()`) is
  implemented and gated; RAM read/write still needs the on-camera helper loaded over
  a connected shell, which isn't wired up yet, so those calls return a clear "blocked
  on enter_service" error rather than fabricate bytes. `MockRam` stands in for the
  tests.

## Build & test

```bash
cd host-injector
cargo check          # type-check
cargo test           # unit tests (profile load, descriptor round-trip, rollback)
cargo run -- --list                                   # list profiles (no camera)
cargo run -- profile_4k_24p_stable --video-standard NTSC --dial MOVIE   # plan + preflight
cargo run -- profile_4k_24p_stable --verify-only \
  --senser-config senser_blobs.json --allow-unverified-usb   # real frames, gated + confirmed
```

> Needs the camera only for `--verify-only` / `--confirm-ram-write`; everything else
> (plan, preflight, tests) runs with no hardware.

## Vendor protocol (`pmca.rs`)

The Sony USB vendor framing (MSC vendor CDB `0x7a`, `ExtCmdHeader`, Senser service
mode + FileControl/MemoryDump, the service PIDs) is transcribed **clean-room** from
the public MIT project [`ma1co/Sony-PMCA-RE`](https://github.com/ma1co/Sony-PMCA-RE),
cited by file + symbol in the source. Ported and unit-tested: the updater-shell
framing (feature `0x23`, tokens `TEST`/`SHEL`/`PUSH`/`PULL`/`RMEM`, the sequence
transfer), the Senser auth handshake + `crypto::sha1_faulty` (stock SHA-1 with the
length field using `(len & 0x1f)*8`, from `pmca/usb/crypto.py`), and the exec
sequence — there is **no `ShellExec` opcode**, so a binary is run by `PUSH`-ing it and
typing its path on the `SHEL` relay (`exec_helper_sequence`).

One thing stays **external** and keeps the end-to-end path from completing on public
MIT alone: the Senser **key tables** (`pmca/usb/constants.py`
`senserKeysSha1`/`senserKeysSha256`, 3 blobs each, hundreds of bytes). Too large to
hand-transcribe safely, so only their cited 8-byte fingerprints are embedded; copy the
real blobs from `constants.py` into a JSON file shaped `{"sha1": [...], "sha256":
[...]}` (3 hex strings each) and pass it via `--senser-config <path>` (or
`OG_SENSER_CONFIG`) — loaded and checked against the cited fingerprints before
`set_senser_keys()` stores it.

The Senser **control + bulk transport** (`SenserIo`) is implemented: `RusbSenserIo`
sends the vendor control request on the still-open MSC handle, releases it, and the
CLI (`main.rs`) polls for the camera's re-enumeration as `054C:0336`, opens it,
discovers its bulk endpoint pair from the config descriptor, and wires it into
`enter_service()` — which then drives the real 3-round challenge/response. The SHA1
reply path is handled; a SHA256 challenge still refuses rather than guess its
response-body layout.

Two gates protect the camera:
- `VENDOR_PROTOCOL_VERIFIED` (compile-time) stays `false` — the handshake and the
  re-enumeration lifecycle above are implemented and unit-tested against mocks, but
  **not yet proven on a live A6700**.
- `--allow-unverified-usb` (runtime, with an interactive `yes` confirm) lets a tester
  send real frames without recompiling, once `VENDOR_PROTOCOL_VERIFIED` would
  otherwise block them.

## Clean-room / safety

No Sony firmware bytes. Geometry words are arithmetic from the target resolution and
come straight from the JSON; firmware-derived payloads stay in git-ignored
`payloads/`. Default is a no-camera plan. Writing needs `--confirm-ram-write`, is
RAM-only, and reverts on a cold boot (battery out ~10 s).
