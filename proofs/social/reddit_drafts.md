# Reddit drafts — ready to paste

Two drafts, for two different audiences. Both describe **read-only / RAM-only**
work; neither claims anything not already verified in [`RESEARCH.md`](../../RESEARCH.md)
and [`README.md`](../../README.md). Fill in the `[ ... ]` placeholders (links,
screenshots, username) before posting — nothing here posts itself.

Gallery images referenced below live in `proofs/hardware-tests/` once tonight's
`--verify-only` + MediaInfo capture checklist (see `proofs/README.md`) is done.

---

## Draft 1 — r/a6700 (Image Gallery post + pinned comment)

**Format:** Reddit Gallery post (multiple images), title below, each image gets
one of the captions below in order, then add the "Pinned comment" text as a
comment on your own post and pin it.

### Title

> True 3:2 Open Gate (3840×2560) on the A6700 — RAM-only, open source, reverts on a battery pull

### Gallery captions (in post order)

1. **MediaInfo — 3840×2560.** Confirmed resolution on a clip recorded with the
   stable chain applied (S-Log3, 23.98p, ~97.6 Mbps). `[screenshot:
   proofs/hardware-tests/mediainfo-3840x2560-<date>.png]`
2. **16:9 vs 3:2 — same scene, full frame.** Left: stock 16:9. Right: Open Gate
   3:2, no crop, no letterbox. `[screenshot:
   proofs/hardware-tests/16x9-vs-3x2-<date>.png]`
3. **Live Ghosting RAW preview.** `--live-ghost` ghosting a composite from a
   folder of `.ARW` files (embedded JPEG previews decoded live) - this is the
   16-bit linear RAW multi-exposure tooling, separate from the Open Gate patch
   itself. `[screenshot/clip: proofs/social/live-ghost-preview.png or .mp4
   (gitignored - host it yourself, e.g. imgur/streamable, and link it)]`

### Post body

RAM-only. Nothing is written to flash, NVRAM, or camera settings — a cold boot
(battery out ~10 s) reverts everything. No Sony firmware bytes in the repo: the
geometry patch is arithmetic computed from the target resolution, and the one
firmware-derived piece (the encoder design) stays an external file you supply
yourself, verified by sha256 before and after, never committed.

**What it actually does:** a single held USB session (Mass Storage → service
mode) chains five verified steps — `L13` (raw write-buffer sizing), `L5`
(sensor drive window, 3876 rows from row 214), `L16` (encoder output size),
`M19` (the stable full encoder design, 483 spans), `S16` (clears the 16:9
letterbox so the rear 3:2 panel shows the whole frame). Every write is
read-verified against its expected stock bytes *before* anything is touched,
read back after, and rolled back automatically on any mismatch.

**Why not the "obvious" high-speed encoder?** There's an `L19` chain that looks
like it should work and doesn't - it rebooted the kernel on the STILL→MOVIE
switch during testing. `M19` is the stable drop-in replacement with the same
3840×2560 result. Every profile in the repo (including the 13 other BIONZ XR
bodies catalogued so far) explicitly excludes an `L19`-style step until an
equivalent `M19` is found and verified.

**Also in this release:** `--raw-blend` and `--live-ghost` - a 16-bit **linear**
RAW multi-exposure blender (`dark`/`bright`/`avg`/`add`, 2..9 `.ARW` files,
genuinely linear light so the math is physically correct, not gamma-space math
dressed up as a preview) and a manual live-ghosting preview window that works
straight off a folder of `.ARW` files.

Code, profiles, and the full write-up: `[repo link]`. MIT, clean-room, no
firmware content. Discord for testers: `[discord link]`.

### Pinned comment (post as a comment on your own thread, then pin it)

Quick FAQ before anyone asks:

- **Is this a firmware mod?** No. RAM-only, volatile, reverts on a battery
  pull. Nothing is flashed.
- **Will this trip any warranty flag / telemetry?** Unverified either way -
  treat it like any other RAM-only vendor-protocol tool: your camera, your
  call, your risk.
- **Does it work on [other body]?** Not yet confirmed on anything but the
  A6700. See the cross-post in r/SonyAlpha / r/FX30 if you want to help change
  that safely.
- **Source / how do I run this myself?** `[repo link]` - read the README
  safety section first, specifically the two gates (`VENDOR_PROTOCOL_VERIFIED`
  + `--allow-unverified-usb`) before pointing anything at your own camera.

---

## Draft 2 — r/SonyAlpha & r/FX30 (cross-community showcase + call for RAM dumps)

**Format:** text post, same body for both subreddits (check each sub's rules
on cross-posting / self-promotion first - this is a draft, not a queued post).

### Title

> Open-source Open Gate RAM project looking for FX30 / ZV-E10 II / FX2 / FX3 / A7 IV owners for safe, read-only RAM dumps

### Post body

Quick context: there's an open-source (MIT, clean-room, no firmware content)
project that unlocked a real **3840×2560 (3:2) Open Gate** recording window on
the **Sony A6700** - RAM-only, verified read-before-write with automatic
rollback, reverts on a battery pull. Full write-up and the actual A6700 profile:
`[repo link]`.

The A6700 is one of **14 BIONZ XR bodies** the project catalogs (same
processor family, grouped by sensor):

| Sensor family | Bodies |
|---|---|
| APS-C 26 MP | A6700 ✅ (verified), **FX30**, **ZV-E10 II** |
| Full-Frame 12.1 MP | A7S III, **FX3**, ZV-E1 |
| Full-Frame 33 MP | **A7 IV**, A7C II, **FX2** |
| Full-Frame 61 MP | A7R V, A7CR |
| Full-Frame Stacked/GS | A1, A1 II, A9 III |

**Only the A6700 is verified.** The other 13 — including **FX30, ZV-E10 II,
FX2, FX3, and A7 IV** — have *locked* skeleton profiles: real step ids, **zero
memory offsets**, nothing guessed or copied from the A6700. They're placeholders
waiting for someone with the actual body to help locate the equivalent sites,
read-only, on their own hardware.

**If you own one of those bodies and want to help**, here's the actual
(read-only, no writes, nothing flashed) process:

1. **`--dump-ram`** — once you're in a Senser-mode session on your body (behind
   the same `--allow-unverified-usb` opt-in + typed confirmation as every other
   real-hardware step), read a candidate memory region to a local file. This
   only reads; it never writes anything back to the camera.
2. **`--scan-dump`** — fully offline, no camera involved at all: search your
   dump for the verified A6700 profile's known byte signatures. A unique match
   becomes a candidate offset; anything ambiguous gets flagged for a human to
   resolve, never guessed.
3. **`--verify-only`** — confirm the candidate offsets actually hold the
   expected bytes on your body before anyone adds them to that body's profile
   for real.

Nothing here writes to your camera. The project explicitly refuses
`--confirm-ram-write` on any profile with zero resolved writes - which is every
non-A6700 profile right now, by design.

Full step-by-step ("Contributing a New BIONZ XR Body"): `[repo link]#contributing`.
Discord if you want to coordinate before diving in: `[discord link]`.

One thing worth knowing up front either way: the A6700's working chain
deliberately **excludes** a faster encoder path (`L19`) that looked promising
but rebooted the camera during testing - the stable one (`M19`) got there
instead. If your body turns out to need something similar, the same rule
applies: nothing ships until it's found *and* verified safe, read-only, first.
