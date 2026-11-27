# RESEARCH — Sony A6700 (ILCE-6700) firmware 2.00

Original hardware findings from this project. Everything here is **read-only
observation** of the running camera's RAM (read-check dumps) plus static analysis —
no Sony firmware bytes are reproduced. Volatile RAM only: a cold boot (battery out
~10 s) reverts every state described here.

Upstream reference: [ArcaneLantern/a6700-open-gate-test](https://github.com/ArcaneLantern/a6700-open-gate-test)
(GPL-3.0) — *referenced, never copied*. The findings below were confirmed
independently on our own body and are stated as facts, not as that project's code.

---

## 1. Display panels confirmed in hardware

The screen step's panel table reports the two physical panels directly:

| Panel | Type | Aspect | Meaning for Open Gate |
|---|---|---|---|
| Rear LCD | **type 3** | **3:2** | Native 3:2 — can show the full open-gate frame edge to edge, no letterbox. |
| EVF (second) | **type 2** | **4:3** | The viewfinder is 4:3, so a 3:2 frame is pillar/letter-boxed in the EVF only. |

This matters: because the **rear panel is natively 3:2**, the `S16` screen step can
clear the 16:9 letterbox words and the open-gate frame fills the rear LCD. The 4:3
EVF cannot, which is expected and not a bug.

Observed screen-step change (rear panel): the panel height word moves
`0x0194` (404) → `0x01E0` (480), i.e. the fit region opens to the full 3:2 panel.

---

## 2. Kernel reboot: L19 (unstable) vs M19 (stable)

Two encoder designs were tried for 3840×2560:

| Design | Spans | Result |
|---|---|---|
| **L19** `ogfile2560_hs_s` (high-speed-only) | 107 | **Kernel reboot** on the STILL → MOVIE switch. The dump taken afterwards reads all-stock because the reboot cleared RAM. |
| **M19** `ogfile2560_full` | **483 (= 475 av-cam.bin + 8 libmpr.so)** | **100 % stable.** Recorded a clean MP4 S-Log3 **3840×2560 @ 23.98p, ~97.6 Mbps**; recording did not stop. |

**Conclusion:** the reboot was caused by the *high-speed-only* encoder (L19), not by
the geometry writes. The stable chain is **L13 + L5 + L16 + M19 + S16**:

| Step | What it changes |
|---|---|
| **L13** | raw write-buffer size words (memory manager) |
| **L5** | sensor drive window (3348 rows @ row 406 → **3876 rows @ row 214**) |
| **L16** | encoder output size (`0x08700F00` 3840×2160 → `0x0A000F00` 3840×2560) |
| **M19** | full encoder design (475 av-cam.bin + 8 libmpr.so spans) |
| **S16** | screen / display fit (full 3:2 rear panel, letterbox cleared) |

The movie size table entry id `0x2D9` flips **3840×2160 → 3840×2560** as part of M19.

> Rule for any port: **use M19, never L19.** The high-speed encoder reboots the body.

---

## 3. Raw buffer capacity — the path to true 3:2 (5952×3968)

The contributed 4K window reads **5952×3876** from sensor row 214. The native 3:2
read-out is **5952×3968** — so the contributed window captures only `3876 / 3968 =
0.977` of the vertical field of view, and its picture ends up **~2.4 % too tall**.

The question was whether the full 3968-row window physically fits the raw write
buffer (`dmmwb`). From the applied `L13` buffer-size word:

```
raw buffer size = 0x016D5A00 = 23,943,680 bytes
row stride      = 6016 bytes            (= 5952 active + 64 padding, one cache line)
buffer rows     = 23,943,680 / 6016 = 3980 rows
```

**The `dmmwb` buffer holds 3980 rows. The true 3:2 window needs 3968 rows → it fits
(12 rows to spare).** That is what opens the door to the exact 3:2 window without
the 97.7 % correction.

> ⚠️ **Not yet run on any A6700.** The true 3:2 window starts at sensor **row 94**
> (first-row register < 256), a range never exercised on this body — expect a possible
> black frame or restart (battery pull clears it). See
> [`profiles/profile_true_3x2_experimental.json`](profiles/profile_true_3x2_experimental.json).

---

## 4. Summary of verified addresses (file offsets / coprocessor)

Geometry words only (arithmetic from the target resolution — not firmware code).
The firmware-derived encoder/sensor/playback payloads are **not** in this repo; the
profiles carry their sha256 fingerprints for verify-before-write only.

| Site | Addr | Stock → Target | Meaning |
|---|---|---|---|
| output size | `0x0199ECC4` | `000f7008` → `000f000a` | height 2160 → 2560 |
| raw buffer ×4 | `0x02580CD8…` | `00123401` → `005a6d01` | buffer sized for 3980×6016 |
| screen height | `0x00E99E6C` | `80029401` → `8002e001` | panel fit 404 → 480 |

Full step/write tables: [`profiles/`](profiles/). Injector: [`opengate_inject.py`](opengate_inject.py).

---

## 5. Open questions

- Does the **power switch** (not a battery pull) clear the RAM patch? Unknown on A6700.
- The **true 3:2 window (5952×3968 from row 94)** has never been run — first light needed.
- **In-camera playback** of 3840×2560 needs the separate `playback_fix` (R19) module,
  which touches executable instructions (higher risk than geometry).
