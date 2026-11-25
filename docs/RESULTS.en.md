# Experimental results — Sony A6700

**🌍 Language: English · [Français](RESULTS.md)**

Validated live on a **Sony A6700 (ILCE-6700)**, firmware **2.00**, USB **PC Remote**
mode (PID **`0x0E78`**, VID `0x054C`), over PTP / Sony "SDIO". Protocol constants
only; no firmware files are included in this repository.

## Summary

| Goal | Status | Evidence |
|---|---|---|
| **Multi-exposure (driven capture)** | ✅ **Working** | Full USB control of multi-frame capture via `ControlDevice(0x9207)` S1/S2; `multi_exposure.py` automates it. |
| **Open Gate 3:2 (video)** | 🔒 **Blocked (application layer)** | `SetExtDevicePropValue(0xD211)=3:2` returns `OK` but is silently ignored; HAITA keeps 16:9 in Video. |

---

## 1. Multi-exposure — complete success

The camera's capture chain is fully controllable over USB, read-only diagnostics
first, then session-only control:

- **Session handshake** (`probe_a6700.py`): `OpenSession(0x1002)` → `SDIO_Connect
  (0x9201)` ph1/ph2/ph3 (each `OK`, 8-byte DATA) → `SDIO_GetExtDeviceInfo(0x9202)`
  (~826 bytes) → `GetAllExtDevicePropInfo(0x9209)` (~8019 bytes, 122 active
  properties in Video mode).
- **Trigger control** (`experiment_a6700.py`, `multi_exposure.py`):
  `ControlDevice(0x9207)` on **S1 `0xD2C1`** (half-press / AF), **S2 `0xD2C2`**
  (full-press / shutter) and **`0xD2C8`** (movie record) — all return `OK`. Button
  values: press = `2`, release = `1`.
- **Automation** (`multi_exposure.py`): optional drive/bracket set via
  `still_capture_mode (0x5013)`, then N frames at a controlled interval, with
  optional read-only PTP download of the new frames and local stacking
  (`average` = multi-exposure blend, `lighten` = star trails).

**Conclusion:** the multi-exposure objective is met with **no permanent modification**
of the camera — everything is session-only control plus local image processing.

```powershell
python multi_exposure.py --confirm-session-write --shots 8 --interval 0.8 \
    --download-dir out/ --stack out/multi.png --stack-mode average
```

---

## 2. Open Gate 3:2 — application-level lock confirmed

`aspect_ratio (0xD211)` is a `Get/Set`, `enabled=1` property. Observed current
values: **`1` (3:2) in Photo mode**, **`2` (16:9) in Video mode**.

Experiment (`experiment_a6700.py --test-aspect-3-2`, in Video mode):

1. read `0xD211` via the `0x9209` stream → `2` (16:9);
2. `SetExtDevicePropValue(0x9205)` write `1` (3:2) → **response `0x2001 OK`**;
3. re-read `0xD211` via `0x9209` → **still `2` (16:9)**.

The write is **accepted then silently ignored**. This experimentally confirms the
static-analysis finding: the **HAITA Feature Manager** enforces
`REC_MOVIE_ASPECT_RATIO_NOT_16_9` for movie recording inside `appFw.so`, **above**
the PTP layer. The PTP property set exposes 3:2, but the application gate overrides
it in Video mode.

**Conclusion:** Open Gate 3:2 video is **not reachable through a PTP property write**.
Any path forward would have to act on the application-layer gate itself (see the
RAM-only investigation plan in the project notes), which is out of scope for this
repository's session-only, no-permanent-write policy.

---

*Reproduce the diagnostics with `probe_a6700.py` (read-only). Writes are opt-in and
session-only via `experiment_a6700.py` / `multi_exposure.py`.*
