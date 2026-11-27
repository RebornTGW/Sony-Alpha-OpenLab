# proofs/ — verified technical context + hardware-test workspace

This folder holds the evidence trail for the project's claims: what's actually
been **verified on real hardware** (read-only observation only — see
[`RESEARCH.md`](../RESEARCH.md)), what's still a **locked, untested skeleton**
(the 14-body BIONZ XR catalog), and the raw material (logs, screenshots,
gallery assets) that backs each. Nothing here is Sony firmware content; see
the root `.gitignore` and [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Layout

| Folder | Holds | Tracked in git? |
|---|---|---|
| `research/` | Architecture notes, protocol write-ups, cross-body comparisons | Yes (text only) |
| `hardware-tests/` | `--verify-only` logs, MediaInfo screenshots, 16:9-vs-3:2 comparison frames | Yes (text/logs); raw video goes in `videos/` instead |
| `social/` | GitHub Social Preview image, Reddit gallery assets, post drafts | Yes |
| `videos/` | Screen recordings / raw capture footage | **No** — gitignored, local only |

`videos/`, any `*.mp4`/`*.MOV`, and any `*.bin` under `proofs/` are gitignored
(see the root `.gitignore`'s `proofs/` section) so a hardware-test session
never bloats the repo with large binaries, by accident or otherwise.

---

## Verified technical context

### A6700 firmware 2.00 — the stable Open Gate chain (M19, not L19)

Two full-encoder designs were tried for 3840×2560 on the real A6700 body (read-only
RAM observation after each test, battery pull between runs):

| Design | Spans | Result |
|---|---|---|
| **L19** `ogfile2560_hs_s` (high-speed-only) | 107 | **Kernel reboot** on the STILL → MOVIE switch. The read-check taken afterwards shows all-stock because the reboot cleared RAM — it never actually ran. |
| **M19** `ogfile2560_full` | 483 (475 `av-cam.bin` + 8 `libmpr.so` spans) | **100% stable.** Recorded a clean MP4, S-Log3, **3840×2560 @ 23.98p, ~97.6 Mbps**; recording did not stop. |

**The verified stable chain is `L13 + L5 + L16 + M19 + S16`** (see
[`RESEARCH.md` §2](../RESEARCH.md#2-kernel-reboot-l19-unstable-vs-m19-stable) and
[`profiles/profile_4k_24p_stable.json`](../profiles/profile_4k_24p_stable.json)):

| Step | What it changes |
|---|---|
| `L13` | raw write-buffer size words (memory manager) |
| `L5` | sensor drive window (3348 rows @ row 406 → 3876 rows @ row 214) |
| `L16` | encoder output size (`0x08700F00` 3840×2160 → `0x0A000F00` 3840×2560) |
| `M19` | full encoder design (the stable 483-span one above) |
| `S16` | screen / display fit (full 3:2 rear panel, 16:9 letterbox cleared) |

**Why `L19` is excluded everywhere in this project** (including from all 5 locked
multi-camera skeletons in `profiles/`): it is the only chain ever observed to crash
the camera. `M19` is the drop-in stable replacement with the same end result. Any
new body's profile follows the same rule — no `L19`-equivalent step gets added
until an `M19`-equivalent is found and verified read-only first.

### Senser service mode (`0x0336`) — the USB path this depends on

Entering service mode is how `host-injector` reaches RAM at all: Mass Storage
(`054C:0E76`) → `StartSenser` control request → the camera re-enumerates as
**`054C:0336`** → a 3-round SHA1/SHA256 challenge/response auth handshake
(`SonySenserAuthDevice.authenticate`, ported clean-room from `ma1co/Sony-PMCA-RE`)
→ FileControl (`writeFile`) and MemoryDump (`readMemory`/`writeMemory`) ops over
that same session. See [`host-injector/src/pmca.rs`](../host-injector/src/pmca.rs)
and [`host-injector/README.md`](../host-injector/README.md) for the full citation
trail.

**`VENDOR_PROTOCOL_VERIFIED` stays `false`.** This compile-time constant is the
project's hard safety lock: every real-hardware vendor frame in `host-injector`
checks it (or the runtime `--allow-unverified-usb` opt-in, which still requires
typing `yes` to an explicit warning) before touching the wire. It flips to `true`
only once the whole Senser path above has been proven end-to-end on a live A6700 -
not before. Tonight's `--verify-only` run is exactly that proof attempt.

### 14-body BIONZ XR comparison (catalog, not yet verified)

All 14 bodies share the BIONZ XR processor; only the **A6700** is hardware-verified.
The other 13 are locked skeletons (`cameras/<id>/profile.json` for USB identity,
plus 5 `profiles/*.json` Open Gate skeletons with **zero resolved writes** - see
["Contributing a New BIONZ XR Body"](../README.md#-contributing-a-new-bionz-xr-body)):

| Sensor family | Bodies | Open Gate skeleton? |
|---|---|---|
| APS-C 26 MP (IMX571) | **A6700** ✅, FX30, ZV-E10 II | `fx30_v5.00`, `zve10m2_v1.00` |
| Full-Frame 12.1 MP | A7S III, FX3, ZV-E1 | `fx3_v6.00` |
| Full-Frame 33 MP | A7 IV, A7C II, FX2 | `a7m4_v4.00`, `fx2_v1.00` |
| Full-Frame 61 MP | A7R V, A7CR | — |
| Full-Frame Stacked / GS | A1, A1 II, A9 III | — |

Closer sensor family to the A6700 (APS-C 26 MP) means the Open Gate memory layout
is *expected* to be closer, not confirmed to be - every non-A6700 body's profile
has zero resolved writes until someone runs `--dump-ram` + `--scan-dump` on real
hardware. No memory offset for a non-A6700 body exists anywhere in this repo.

---

## Checklist — tonight's `--verify-only` + MediaInfo capture

Read-only. No write happens during any of this (`--verify-only`, never
`--confirm-ram-write`).

1. [ ] Camera in Mass Storage mode (`054C:0E76`), `host-injector` built
       (`cd host-injector && cargo build --release`).
2. [ ] `senser_blobs.json` present (Senser key tables, external MIT data - see
       `host-injector/README.md`). Never commit this file (already gitignored).
3. [ ] Run:
       ```bash
       cd host-injector
       cargo run --release -- profile_4k_24p_stable --verify-only \
         --senser-config senser_blobs.json --allow-unverified-usb
       ```
       Type `yes` at the confirm prompt. Save the full console output to
       `proofs/hardware-tests/verify-only-<date>.log`.
4. [ ] If `enter_service()` succeeds: this is the first live proof the Senser
       auth handshake works end-to-end on real hardware - note the result
       plainly in the log (success *and* failure are both useful data).
5. [ ] If every site reads back as expected stock: screenshot the terminal
       output into `proofs/hardware-tests/` (`verify-only-<date>.png`).
6. [ ] Record (or re-use) a clip with the already-verified M19 chain applied via
       the Python path, pull it to MediaInfo, screenshot the **3840x2560**
       resolution field into `proofs/hardware-tests/mediainfo-3840x2560-<date>.png`.
7. [ ] Capture one 16:9 stock frame and one 3:2 Open Gate frame of the same
       scene for a side-by-side comparison image, save under
       `proofs/hardware-tests/`.
8. [ ] Do **not** flip `VENDOR_PROTOCOL_VERIFIED` to `true` from a single run -
       that change happens deliberately, in its own commit, once the result is
       solid and reviewed.
