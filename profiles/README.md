# Open Gate profiles (declarative patch tables)

These JSON files are plain data — no code, no Sony firmware bytes. Each describes
one volatile-RAM Open Gate state for the **Sony A6700 (ILCE-6700, firmware 2.00)**
as a list of steps and writes. `opengate_inject.py` reads them and applies a whole
profile in one held service-mode USB session.

They are built **clean-room** from read-only RAM read-backs of successful hardware
tests, not from GPL source:

| Profile | Status | What it is |
|---|---|---|
| `profile_4k_24p_stable` | **verified** | 3840×2560 (3:2) with the contributed full encoder (M19). The chain that recorded a clean S-Log3 MP4 at 23.98p / 97.6 Mbps. |
| `profile_true_3x2_experimental` | experimental | Exact native 3:2 window 5952×3968 from row 94. Removes the ~2.4 % height stretch. **Never run on any A6700.** |
| `playback_fix` | experimental | Optional R19 add-on so the camera plays its own 3840×2560 clips. |
| `fx30_v5.00`, `zve10m2_v1.00`, `fx2_v1.00`, `fx3_v6.00`, `a7m4_v4.00` | experimental, **locked skeleton** | Real `L13`/`L16`/`S16` step ids, **zero resolved writes** — no memory offset on a non-A6700 body is guessed. `host-injector` refuses `--confirm-ram-write` on a profile with zero resolved writes. See the root README's ["Contributing a New BIONZ XR Body"](../README.md#-contributing-a-new-bionz-xr-body) for how to fill one in via `--dump-ram` + `--scan-dump`. `L19` is deliberately excluded from all five (see `RESEARCH.md` on the kernel-reboot risk). |

## What is in a profile, and what is not

A write is one of two kinds:

* **geometry** — bytes that are arithmetic from the target resolution (output size,
  raw-buffer size, screen fit words). These carry literal `stock` and `target` hex,
  plus a `derivation` showing the math. Safe to ship: they are our computed numbers,
  not copied firmware.
* **firmware-derived payload** (`encoder_blob`, `sensor_registers`, `code_patch`) —
  the encoder design, sensor-register cells, and playback instruction patches. These
  carry **only** an address, length, and `sha256` fingerprints (stock + target) and a
  `payload_ref` to an external file. **No payload bytes are in this repo.** Supply the
  `.bin` from the GPL kit; it lands in `payloads/` (git-ignored). The injector verifies
  it by sha256 before and after.

Short fingerprints are the leading hex of the full sha256, taken from the read-check
report. They identify a blob; they do not reproduce it.

## Verify-before-write

Every apply first reads each site and checks it holds the expected `stock`. Any
mismatch aborts the whole profile before a single byte is written (wrong firmware, or
already patched). Writes go out as whole 64-byte lines, are read back, and self-undo
on mismatch — all inside the one open session.

## Safety

RAM only. A cold boot (battery out ~10 s) reverts everything. Nothing is written to
flash, NVRAM, or settings. Required USB path: Mass Storage `0x054C:0x0E76` → service
mode `0x054C:0x0336` (NOT PC Remote `0x0E78`).
