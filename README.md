# Sony-Open-Gate-Lab

**🌍 Language: English · [Français](README.fr.md)**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v0.1.0--alpha-blue.svg)](#)
[![Status](https://img.shields.io/badge/status-active%20development-orange.svg)](#)
[![Discord](https://img.shields.io/badge/Discord-Sony%20Alpha%20OpenLab-5865F2?logo=discord&logoColor=white)](https://discord.gg/Zr72h6AFa5)

An **open-source toolkit for Sony Alpha cameras**, developed and tested first on the
**Sony A6700 (ILCE-6700)**, with an architecture designed to extend to other Sony
bodies over time.

The toolkit combines three layers, each with its own safety level:

- **Read-only USB probe** (PTP / Sony "SDIO") — open a session, read device info and
  extended property descriptors; issues no write, setting, or trigger command.
- **Opt-in session Multi-Exposure** — guarded capture + local frame stacking;
  session-only, nothing is persisted on the camera.
- **Volatile RAM-only Open Gate research** — read-only by default; any write is
  in-RAM, opt-in, and gone at power-off / battery pull.

> ⚠️ **Independent, unofficial project.** Not affiliated with Sony. Use at your own
> risk, for interoperability and personal study only.
>
> 🚧 **Active development.** This project is actively developed and updated
> regularly — expect frequent changes while the architecture matures.

---

## ✅ Current verified state (Sony A6700 v2.00)

Proven **live on real hardware** (firmware 2.00, PC Remote `PID 0x0E78`):

- **USB telemetry:** session handshake OK; **61 vendor `0x92xx` opcodes** enumerated;
  `GetAllExtDevicePropInfo (0x9209)` ~8019 B (122 active props).
- **Capture control:** `ControlDevice (0x9207)` S1 `0xD2C1` / S2 `0xD2C2` / movie-rec
  `0xD2C8` all return `OK`.
- **Image retrieval:** full-res frame pulled from `0xFFFFC001` (**~31.2 MB RAW**), JPEG
  or `.ARW`, via `GetObjectInfo` + `GetObject`.
- **Multi-exposure:** `multi_exposure.py` live capture + the 4 Fujifilm blend modes
  (`additive`/`average`/`bright`/`dark`, + `screen`) working end-to-end.
- **Open Gate (research):** sensor + encoder tables for **3840×2560** statically
  mapped; the 3:2 menu switch is blocked at the app layer (HAITA) — see
  [`docs/RESULTS.md`](docs/RESULTS.en.md). RAM-only path is research, not shipped.

---

## 🚀 Quickstart (4 steps)

1. **Install** — Python 3.9+, then `pip install -r requirements.txt`
   (see [Installation](#-installation-windows)).
2. **Driver** — set the camera to **PC Remote** USB mode and bind **WinUSB** to its
   interface with **Zadig**. [How →](#2-winusb-driver-via-zadig)
3. **Probe (read-only)** — `python probe_a6700.py` to confirm the USB handshake and
   list the exposed properties.
4. **Multi-exposure (opt-in)** — `python multi_exposure.py --shots 2 --live-overlay`
   to capture and blend frames (session-only).

---

## 🎯 Project scope

The research is **strictly limited to two goals**, with **no permanent modification**
of the camera:

1. **Open Gate 3:2** — investigating the feasibility of recording video in the full
   3:2 sensor aspect ratio ("open gate").
2. **Multi-exposure** — investigating multi-frame capture mechanisms.

Both goals are approached through **static analysis** and **read-only USB
diagnostics**. This is not a general-purpose control tool, a shutter/record trigger,
or a firmware modifier. Any future feature stays bounded to these two goals and to
the safety approach below.

---

## 📷 Supported cameras & roadmap

The toolkit is built on the Sony Alpha remote protocol (PTP + Sony "SDIO" vendor
extension) and the Open Gate RAM patch path, both largely shared across the
**BIONZ XR** line. 14 BIONZ XR bodies are catalogued under
[`cameras/`](cameras/), grouped by sensor family (closer family = closer
expected memory layout to the verified A6700):

| Sensor family | Bodies | Status |
|---|---|---|
| APS-C 26 MP (IMX571) | **A6700** ✅, FX30, ZV-E10 II | A6700 verified (fw 2.00); others await `--dump-ram` / `--scan-dump` |
| Full-Frame 12.1 MP | A7S III, FX3, ZV-E1 | awaiting `--dump-ram` / `--scan-dump` |
| Full-Frame 33 MP | A7 IV, A7C II, FX2 | awaiting `--dump-ram` / `--scan-dump` |
| Full-Frame 61 MP | A7R V, A7CR | awaiting `--dump-ram` / `--scan-dump` |
| Full-Frame Stacked / GS | A1, A1 II, A9 III | awaiting `--dump-ram` / `--scan-dump` |

Older **BIONZ X** bodies (A6400, A6600, ZV-E10 Mark I) are a different protocol
generation and are not catalogued here yet.

Two separate catalogs, by design:

- **[`cameras/`](cameras/)** — USB identity (VID/PID, capture handles) for the
  PTP/SDIO remote-control tools (`probe_a6700.py`, `experiment_a6700.py`,
  `multi_exposure.py`). Load via `from cameras import load_profile`.
- **[`profiles/`](profiles/)** (consumed by [`host-injector/`](host-injector/)) —
  the Open Gate RAM patch tables. Only `profile_4k_24p_stable` is verified; the
  per-body skeletons (`fx30_v5.00`, `zve10m2_v1.00`, `fx2_v1.00`, `fx3_v6.00`,
  `a7m4_v4.00`) are **locked**: real step ids, zero resolved writes, no
  fabricated offsets. See
  ["Contributing a New BIONZ XR Body"](#-contributing-a-new-bionz-xr-body) below.

> ✅ = actively tested · others = planned/placeholder. Compatibility is validated
> per body; a code being present in the protocol does not mean it is exposed on
> every model, and model codes/PIDs for non-A6700 bodies are unconfirmed until
> checked on hardware. Want your body supported? See
> [Community & ideas](#-community--ideas).

---

## 🧪 Safety approach — RAM-only first

As a safety measure, features are first developed and tested **in volatile memory
only (RAM-only)** over USB:

- changes live in the camera's RAM and are **erased on reboot / battery removal**;
- **nothing is written to persistent storage or firmware**;
- a **permanent mode would only ever be considered later**, if and only if safety
  and stability are **fully proven** — and even then as an explicit, opt-in step.

The current reference tool (`probe_a6700.py`) goes one step further: it is strictly
**read-only** and issues no RAM write at all.

---

## 🔒 Safety scope (read-only probe)

`probe_a6700.py` is **strictly read-only**:

| Issued (read / negotiation) | **Never issued** |
|---|---|
| `OpenSession` (0x1002) | `SetExtDevicePropValue` (0x9205) |
| `GetDeviceInfo` (0x1001) | `ControlDevice` (0x9207) → S1 / S2 / Movie Rec |
| `SDIO_Connect` (0x9201) | `SendObject`, deletion, formatting |
| `GetExtDeviceInfo` (0x9202) | firmware update, settings writes |
| `GetExtDevicePropDesc` (0x9203) | any other operation |
| `CloseSession` (0x1003) | |

Every operation is validated against a **whitelist** (`READ_ONLY_OPS`) in the code:
an unlisted opcode raises an exception **before** anything is sent to the camera. The
PTP data phase is used for **reception only**.

This repository contains **no files extracted from the Sony firmware** (see
`.gitignore`). The PTP codes used here are public protocol constants (PTP /
ISO 15740) and the independently documented Sony vendor space.

---

## 🛡️ Security Architecture & BIONZ X Guardrails

Not every tool here talks to the camera the same way, and not every protocol
has been checked against every processor generation. This table is the quick
reference for which is which:

| Tool / flag | Protocol | BIONZ XR (A6700 + the 13-body catalog) | BIONZ X (A6400, A6600, A6100, A7 III, A7C, …) |
|---|---|---|---|
| `probe_a6700.py`, `experiment_a6700.py` | PTP / Sony "SDIO" vendor extension | ✅ works | Expected to work (same PTP/SDIO family) — **not yet validated** on a BIONZ X body |
| `multi_exposure.py` (`--raw-blend`, `--live-ghost`) | Generic: PTP capture + local RAW decode (`rawpy`) / image processing | ✅ works | ✅ works — camera-generation-agnostic, no vendor-specific protocol involved |
| `monitor_hud.py` | Generic: reads frames from a webcam/video/image source, no camera protocol of its own | ✅ works | ✅ works — same reason as above |
| `ram_opengate.py --probe-msc` | Standard SCSI (INQUIRY / TEST UNIT READY / READ CAPACITY) | ✅ works | Expected to work (standard SCSI, not Sony-specific) — **not yet validated** |
| **`opengate-rs.exe`** (`host-injector`) — **RAM injection, `--verify-only`, `--dump-ram`, `--scan-dump`** | **Senser `0x0336` service mode** (clean-room from `ma1co/Sony-PMCA-RE`) | ✅ the only thing this protocol is modeled for | 🛑 **refused outright** — see below |

**The guardrail is real code, not just a table.** `host-injector`'s
`usb::open_a6700()` — the single entry point every one of its real-hardware
actions goes through, `--plan`/`--verify-only`/`--confirm-ram-write`/
`--dump-ram` alike — scans every connected Sony-VID USB device first and
refuses immediately, before a single SCSI vendor packet is sent, if a known
BIONZ X PID is on the bus:

| PID | Body |
|---|---|
| `0x0C68` | A6400 |
| `0x0C9F` | A6600 |
| `0x0C9B` | A6100 |
| `0x0C34` | A7 III |
| `0x0D0A` | A7C |

(`host-injector/src/camera.rs` — not an exhaustive list of every BIONZ X body
or PID, just the known-incompatible ones checked so far. An unlisted PID is
not thereby assumed safe; `VENDOR_PROTOCOL_VERIFIED`/`--allow-unverified-usb`
still gate everything else as usual.) **If you have a BIONZ X body, use
`multi_exposure.py` (`--raw-blend` / `--live-ghost`) or `monitor_hud.py`
instead** — both are camera-generation-agnostic and already work there.

---

## 📦 Installation (Windows)

### 1. Python and dependencies

Python 3.9+ recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

`pyusb` requires the native **libusb-1.0** library. On Windows the simplest path is
to install the **WinUSB** driver on the camera's interface with **Zadig** (next
step): pyusb will then use the libusb backend provided by WinUSB. If needed, drop a
64-bit `libusb-1.0.dll` next to the script or in `C:\Windows\System32`.

### 2. WinUSB driver via Zadig

By default Windows attaches its own "camera" driver (WPD/PTP) to the interface,
which prevents pyusb from accessing it. Zadig lets you switch that interface to
**WinUSB**.

1. Power **on** the camera and set **Menu → Network/USB → USB Connection Mode** to
   **PC Remote** (or **PC (PTP)**), then connect it over USB.
2. Download Zadig from the official site: https://zadig.akeo.ie/
3. Run Zadig **as administrator**.
4. Menu **Options → List All Devices**.
5. In the drop-down, select the camera's interface
   (e.g. "ILCE-6700" / "Sony …"; the PTP/Still Image interface).
6. To the right of the arrow, pick **WinUSB** as the target driver.
7. Click **Replace Driver** (or **Install Driver**) and confirm.

> ⚠️ **One WinUSB bind per USB PID.** The camera exposes a **different USB PID per
> mode**, and Windows treats each PID as a separate device — so you bind **WinUSB /
> libusb-win32** once per PID:
>
> | PID | Mode | Used by |
> |---|---|---|
> | `054C:0E78` | PC Remote | `probe_a6700.py`, `multi_exposure.py` |
> | `054C:0E76` | Mass Storage | `ram_opengate.py`, `opengate_inject.py` (entry) |
> | `054C:0336` | Service mode | Open Gate RAM path (re-enumerates from `0E76`) |
>
> Re-run Zadig and bind **WinUSB** again after switching modes / when a new PID
> appears. To revert a binding: *Device Manager → the interface → Uninstall device*
> → unplug/replug.

> 💡 **Reversible.** To make Windows recognize the camera as a normal device again:
> *Device Manager → the interface → Uninstall device*, then unplug/replug (Windows
> reinstalls its WPD driver). You can also simply change the camera's USB mode.

### Linux (alternative)

```bash
sudo apt install libusb-1.0-0
pip install -r requirements.txt
```
Grant non-root USB access with a udev rule:
```
# /etc/udev/rules.d/70-sony-a6700.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="054c", MODE="0660", GROUP="plugdev"
```
If needed, release the interface from `gphoto2`/PTP (`gvfs-gphoto2`) before running.

---

## ▶️ Usage

```powershell
# Auto-detect the Sony body (VID 0x054C)
python probe_a6700.py

# Standard PTP only (stops after GetDeviceInfo)
python probe_a6700.py --no-sdio

# Full code lists (all vendor opcodes & all exposed properties)
python probe_a6700.py --verbose

# Also send the SDK handshake (SetRemoteSdkInfo 0x9214, session-only write)
python probe_a6700.py --sdk-handshake

# Force a specific USB PID
# (A6700 in PC Remote mode = 0x0E78, confirmed on firmware 2.00)
python probe_a6700.py --pid 0x0E78
```

On the A6700, `GetExtDevicePropValue (0x9204)` returns `0x2005` (Operation Not
Supported), so the probe reads the **real current values from the
`GetAllExtDevicePropInfo (0x9209)` stream** in step `[5b]` (for `still_capture_mode`,
`aspect_ratio`, `file_format_movie`, `recording_setting_movie`,
`recording_frame_rate_setting_movie`), decodes selected entries in `[4c]`, and also
probes `GetExtDeviceProp (0x9251)` read-only in `[5c]`. `--sdk-handshake` is the one
exception to the read-only default (see the note above); everything else the probe
does stays read-only.

Code lists (vendor opcodes in `[2b]`, exposed properties in `[4]`/`[4b]`) are
**compact by default**; pass `--verbose` for the full per-code listing. Step `[4b]`
runs the read-only `SDIO_GetAllExtDevicePropInfo (0x9209)` to show which video
`0xD2xx` properties the body reports in its global stream.

> ℹ️ **About video properties & `SetRemoteSdkInfo (0x9214)`.** On the A6700,
> `file_format_movie (0xD241)` / `recording_setting_movie (0xD242)` can return an
> empty descriptor even with the mode dial on Video/M. Static analysis of
> `libInfraRemote.so` shows property visibility is driven by a per-property
> `IsEnable` flag (`MrpwDeviceManager::UpdateInternalPropValueAndIsEnable`) tied to
> camera state, and that `SetRemoteSdkInfo (0x9214)` is the handshake step that
> registers the host SDK version/model. `0x9214` **sends data to the camera**
> (session handshake, not a settings write), so it is deliberately **kept out of the
> read-only whitelist**; enabling it would be a separate, explicit opt-in.

> 📌 **Known A6700 PID:** `0x0E78` in **PC Remote** USB mode (confirmed live on
> firmware **2.00**). The PID differs per USB connection mode and per body.
>
> ✅ **Validated live (A6700, firmware 2.00).** The full read-only sequence was
> confirmed on real hardware: `SDIO_Connect(0x9201)` ph1/ph2/ph3 each return
> `OK (8 bytes data)`, `SDIO_GetExtDeviceInfo(0x9202)` returns ~826 bytes,
> `GetAllExtDevicePropInfo(0x9209)` returns ~8019 bytes (122 active properties in
> Video mode), and `GetExtDevicePropDesc` decodes the current value + allowed values
> (e.g. `still_capture_mode` as a clean enum, `aspect_ratio`). `GetExtDevicePropValue
> (0x9204)` is **not supported** on this dataset (`0x2005`), so current values are
> read from the `0x9209` stream.
>
> ✅ **Control validated (session-only writes).** `ControlDevice(0x9207)` triggers
> were confirmed `OK` on hardware: **S1** (`0xD2C1`) + **S2** (`0xD2C2`) press/release
> (multi-frame capture) and **movie record** (`0xD2C8`) start/stop. Full USB control
> of capture and recording works.
>
> 🔒 **Application-level HAITA lock proven.** `SetExtDevicePropValue(0xD211)` with `1`
> (3:2) returns `OK`, yet re-reading via `0x9209` shows `aspect_ratio` stays at `2`
> (16:9) in Video mode. This experimentally confirms that the **HAITA Feature Manager**
> (`REC_MOVIE_ASPECT_RATIO_NOT_16_9`) filters the 3:2 switch at the application layer
> (`appFw.so`), beyond the PTP protocol: the command is accepted then silently ignored.
> Open Gate 3:2 video is **not** reachable by a simple property write.

### Expected output (example, A6700 firmware 2.00)

```
=== probe_a6700: READ-ONLY USB diagnostic ===

[+] PTP device opened (VID 0x054C PID 0x0E78, interface #0).

[1] OpenSession(0x1002)          -> OK
[2] GetDeviceInfo(0x1001)        -> OK (… bytes)
      Manufacturer     : Sony Corporation
      Model            : ILCE-6700
      Firmware version : 2.00
      Serial number    : xxxxxxxx
      Vendor extension : id=0x11 "Sony PTP Extensions"
      Operations       : … (vendor 0x92xx: 61)
      Properties       : …

[2b] Vendor operations 0x92xx (61):
       0x9201  SDIO_Connect
       0x9202  SDIO_GetExtDeviceInfo
       0x9203  GetExtDevicePropDesc
       …       …
[3] SDIO_Connect(0x9201) ph1     -> OK
[3] SDIO_Connect(0x9201) ph2     -> OK
[4] SDIO_GetExtDeviceInfo(0x9202)-> OK (… bytes)
[3] SDIO_Connect(0x9201) ph3     -> OK
[5] GetExtDevicePropDesc still_capture_mode (drive mode) -> OK (… bytes)
[5] GetExtDevicePropDesc aspect_ratio                    -> OK (… bytes)
[5] GetExtDevicePropDesc file_format_movie               -> OK (… bytes)

[+] CloseSession(0x1003)         -> session closed.
```

(Exact values depend on the body and firmware version.)

---

## 📖 Reference — key PTP codes (A6700)

Extracted by independent static analysis. Protocol constants only (no firmware data
embedded). Only **read** codes are issued by `probe_a6700.py`; the `ControlDevice`
"buttons" are **documented but never triggered** by this tool.

### Operation opcodes

| Opcode | Operation | Type |
|---|---|---|
| 0x1001 | `GetDeviceInfo` | standard PTP (read) |
| 0x1002 / 0x1003 | `OpenSession` / `CloseSession` | standard PTP |
| 0x1009 / 0x101B | `GetObject` / `GetPartialObject` | standard PTP (read) |
| 0x9201 | `SDIO_Connect` | Sony vendor (handshake) |
| 0x9202 | `SDIO_GetExtDeviceInfo` | Sony vendor (read) |
| 0x9203 / 0x9204 | `GetExtDevicePropDesc` / `GetExtDevicePropValue` | Sony vendor (read) |
| 0x9205 | `SetExtDevicePropValue` | Sony vendor (**write — not used**) |
| 0x9207 | `ControlDevice` | Sony vendor (**actuation — not used**) |

### Properties (`DevicePropCode`) — read

| Code | Symbolic name | Usage |
|---|---|---|
| **0x5013** | `still_capture_mode` | Drive mode (single / continuous / self-timer / **bracket**) |
| **0xD211** | `aspect_ratio` | image aspect ratio (3:2 / 16:9 / 4:3 / 1:1) |
| **0xD241** | `file_format_movie` | movie file format (XAVC HS / S / S-I) |
| **0xD242** | `recording_setting_movie` | recording setting (resolution / bitrate) |
| 0xD286 | `recording_frame_rate_setting_movie` | movie frame rate |
| 0xD253 / 0xD287 | `file_format_still` / `compression_file_format_still` | still format |
| 0xD20D / 0xD21E | `shutter_speed` / `iso_sensitivity` | exposure |
| 0x5007 / 0x5010 | `f_number` / `exposure_bias_compensation` | exposure |

### `ControlDevice` actions (⚠️ **write — documented, not issued by this tool**)

| Code | Symbolic name | Effect |
|---|---|---|
| **0xD2C1** | `s1_button` | **half-press (AF)** |
| **0xD2C2** | `s2_button` | **full-press (photo release)** |
| **0xD2C8** | `movie_rec_button` | **movie record start/stop** |
| 0xD2E6 | `s1_and_s2_button` | S1 + S2 combined |
| 0xD2C3 / 0xD2C4 / 0xD2C9 | `ael_button` / `afl_button` / `fel_button` | AE / AF / flash locks |

> These actions change the camera's physical state (shutter, recording). They are
> listed here **for reference** and are **not** implemented in `probe_a6700.py`,
> which stays strictly read-only.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "No Sony USB device found" | Body off, asleep, or data cable missing. Check USB mode = PC Remote. |
| `USBError: [Errno 5]` / access denied | WinUSB driver not installed on the interface → re-run Zadig. |
| "no usable PTP interface" | Wrong USB mode (Mass Storage/MTP) → switch to PC Remote / PTP. |
| `NoBackendError` | `libusb-1.0.dll` not found → install WinUSB (Zadig) or drop the DLL. |
| Timeout after OpenSession | Another app (Imaging Edge, gphoto2) holds the body → close it. |

---

## 🧪 Session-only experiments (`experiment_a6700.py`)

`probe_a6700.py` stays **strictly read-only**. For controlled tests that actually
write to the camera, a **separate** script `experiment_a6700.py` performs
**session-only, non-persistent** operations (everything it changes lives in RAM and
is erased on reboot / battery removal — nothing is written to storage or firmware).

It refuses to run without the explicit flag **`--confirm-session-write`**, and prints
the PTP response code of every operation so you can see what the body accepted.

```powershell
# Try to set aspect_ratio (0xD211) to 3:2 in Video mode, then read it back
python experiment_a6700.py --confirm-session-write --test-aspect-3-2

# Controlled multi-frame trigger: optional drive-mode set + S1/S2 sequence
python experiment_a6700.py --confirm-session-write --test-burst-trigger --drive-value 0x2

# Record a short clip to inspect the resulting MP4 resolution on the SD card
python experiment_a6700.py --confirm-session-write --test-movie-rec --rec-seconds 2
```

| Experiment | What it does (session-only) |
|---|---|
| `--test-aspect-3-2` | reads `aspect_ratio` (0xD211) current value from the `0x9209` stream, `SetExtDevicePropValue(0x9205)` writes `1` (3:2), re-reads it, and reports whether the body actually switched `2`→`1` or accepted-then-ignored it. |
| `--test-burst-trigger` | optionally sets `still_capture_mode` (0x5013) via `--drive-value`, then runs `ControlDevice(0x9207)`: `S1` (0xD2C1) press/release + `S2` (0xD2C2) press/release. |
| `--test-movie-rec` | toggles `movie_rec_button` (0xD2C8) via `ControlDevice(0x9207)` to start, waits `--rec-seconds`, then stops - so you can check the recorded MP4's real resolution (e.g. after `--test-aspect-3-2`). |

> ⚠️ These writes change the camera's **live session state** (and `--test-burst-trigger`
> **takes a picture**). They are volatile, but use them deliberately, on your own
> hardware, with no important card contents. The S1/S2 values and SDK payload are
> best-effort and may need per-body adjustment. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 🎞️ Automated multi-exposure (`multi_exposure.py`)

Built on the **validated** session-only control commands (`still_capture_mode`
0x5013 + `ControlDevice` 0x9207 S1/S2), `multi_exposure.py` captures **N frames at a
controlled interval** and can optionally **stack** them locally using the four
**Fujifilm multi-exposure modes**. It requires `--confirm-session-write` and takes
real pictures.

### Fujifilm multi-exposure modes (`--stack-mode`)

All stacking is done in **float32 linear space** (8-bit JPEG or 16-bit decoded RAW/TIFF
if `rawpy`/`tifffile` are installed), so dark gradients don't band.

| Mode | Alias | Math | Best for |
|---|---|---|---|
| `additive` | | `clip(ΣframeN)` | true film-style additive exposure |
| `average` | | `Σframe / N` | balanced, classic multi-exposure |
| `bright` | `lighten` | per-pixel **max** | light trails, stars, bright subject on dark bg |
| `dark` | `darken` | per-pixel **min** | silhouettes against a bright background |
| `screen` | | `1-(1-A)(1-B)` | soft Fuji/Canon double-exposure look |

> ⚠️ **`additive` adds light.** Two frames add about **+1 EV**, N frames **+log₂(N) EV**.
> Dial in negative exposure compensation on the camera or the highlights clip — the
> tool prints the exact amount when you pick `additive`.

```powershell
# 5 frames, 1s apart (AF before each shot)
python multi_exposure.py --confirm-session-write --shots 5 --interval 1.0

# Additive film-style multi-exposure, auto-download each frame (0xFFFFC001)
python multi_exposure.py --confirm-session-write --shots 4 --no-af \
    --download-dir out/ --stack out/multi.png --stack-mode additive

# OFFLINE star trails: stack a folder, no camera (bright = per-pixel max)
python multi_exposure.py --stack-dir ./frames --stack trails.png --stack-mode bright

# --stack-all: render ALL 4 core modes from the same frames to compare
python multi_exposure.py --stack-dir ./frames --stack out/me.png --stack-all
#   -> out/me_additive.png  out/me_average.png  out/me_bright.png  out/me_dark.png

# OFFLINE 16-bit linear RAW blend: 2..9 Sony .ARW files -> 16-bit TIFF
python multi_exposure.py --raw-blend frame1.ARW frame2.ARW frame3.ARW \
    --mode avg --output out/merged.tiff
# RAW modes: dark, bright, avg, add

# Fujifilm step-by-step: [Enter] next / [r] retake last / [q] finish & stack
python multi_exposure.py --confirm-session-write --interactive --shots 3 \
    --download-dir out/ --stack out/double.png --stack-mode screen

# Real-time Live View overlay (align frame 2 over frame 1 live; Space to capture)
python multi_exposure.py --confirm-session-write --live-overlay --shots 2 \
    --download-dir out/ --stack out/double.png --stack-mode screen --overlay-opacity 0.5

# Manual live ghost preview: webcam index, video file, or folder of images
python multi_exposure.py --live-ghost --source 0 --shots 3 --mode avg
# Offline preview from a video or image folder (.ARW shows its embedded JPEG
# preview); Space freezes, S saves early (>= 2 shots), R resets, Q quits
python multi_exposure.py --live-ghost --source ./frames --shots 3 --mode bright

# --live-ghost + -o: a folder of .ARW + a .tiff output runs the full-resolution
# 16-bit linear RAW stack (blend_raw_files) once --shots is reached or on S;
# any other source/output combination saves the composited preview instead
python multi_exposure.py --live-ghost --source ./raw_frames --shots 3 --mode add -o out/ghost.tiff
```

| Option | Purpose |
|---|---|
| `--shots N` / `--interval S` | capture N frames, S seconds apart |
| `--no-af` | skip the S1 (AF) half-press; S2 full-press only |
| `--drive-value V` | set `still_capture_mode` (0x5013) first (continuous/bracket enum value) |
| `--download-dir DIR` | auto-download each frame via the Sony PC-save handle `0xFFFFC001` (read-only `GetObject`) |
| `--stack OUT` / `--stack-dir DIR` | stack output file / offline source folder |
| `--stack-mode` | `additive`, `average`, `bright`/`lighten`, `dark`/`darken`, `screen` |
| `--stack-all` | render all 4 core Fujifilm modes from the same frames at once |
| `--interactive` / `--manual-step` | step-by-step: `[Enter]` next / `[r]` retake last / `[q]` finish & stack |
| `--live-overlay` / `--overlay-opacity` | live window blending the feed (`0xFFFFC002`) over frame 1; Space captures |
| `--live-ghost` / `--source` | OpenCV preview from webcam index (e.g. `0`), video, or image folder (`.ARW` shown via its embedded JPEG preview); `--shots` 2..9; Space captures, `S` saves early, `R` resets, `Q` quits |
| `-o` / `--output` | with `--raw-blend`: required `.tiff` output. With `--live-ghost`: optional - saved on reaching `--shots` or `S`; a RAW `.tiff` stack if every captured shot was an `.ARW`, else the composited preview |

**Native double-exposure experience.** `--interactive` reproduces the Fujifilm
in-camera flow: shoot frame 1, then for each next frame choose `[Enter]` to shoot,
`[r]` to retake the last one, or `[q]` to finish — a running preview is written after
each shot so you can judge the composition. `--live-overlay` goes further: it shows the
real-time Live View superimposed over the previous frame(s) so you can align before
pressing **Space**. The overlay window uses `tkinter` (bundled with Python) + Pillow —
no extra dependency.

`--live-ghost` is a separate manual preview using a webcam/UVC device or an offline
video/image folder. It shows the current frame blended with captured frames and a
`Manual k/N exp. [mode]` HUD. An image folder of Sony `.ARW` files works too: each one's
embedded JPEG preview (`rawpy`'s `extract_thumb()`) is decoded for the live window — a
file with no JPEG thumb, or `rawpy` not installed, is skipped with a clear message
rather than failing the whole session. Install the optional dependencies with
`pip install opencv-python rawpy`; press **Space** to freeze a shot, **S** to save
early (needs `-o` and >= 2 captured shots), **R** to reset, or **Q** to quit. Available
modes are `dark`, `bright`, `avg`, and `add`.

**Saving a `--live-ghost` result (`-o`).** Reaching `--shots` auto-saves (then ends the
session, same as `S` immediately followed by `Q`); `S` saves early once at least 2
shots are captured, without ending the session. What gets written depends on the
captured sources: if every one of them was an `.ARW` file (the folder-of-RAWs case)
*and* `-o` ends in `.tiff`, the save runs the same full-resolution 16-bit linear
`blend_raw_files` stack `--raw-blend` uses - not the lower-res JPEG-thumbnail preview.
Any other case (webcam/video frames, a mix, or a non-`.tiff` output) saves the
composited preview image OpenCV already has on screen.

**Auto-download (PC Remote).** In PC Remote mode the A6700 doesn't expose
`GetObjectHandles`; it places the last captured image on the special Sony handle
**`0xFFFFC001`**, which `--download-dir` reads after each shot via `GetObject`. The
26 MP buffer isn't ready instantly: each poll calls **`GetObjectInfo (0x1008)` first**
(the body only sizes the object once asked) and fetches only when its size > 0, for
up to ~3 s. The saved file keeps its real extension from `GetObjectInfo` — **JPEG or
RAW `.ARW`** (not just `FF D8`). To route images even if the menu is on "Camera only",
the tool sends `SetContentsTransferMode (0x9212)` during connect (disable with
`--no-pc-transfer`; try `--xfer-mode 2` if mode 1 doesn't route). Use `--verbose` to
see per-poll response codes and sizes. Setting the camera's **Save Destination to
"PC+Camera" or "PC only"** is still the most reliable.

**Offline stacking.** `--stack-dir DIR --stack OUT` (without `--confirm-session-write`)
stacks images from a folder **without touching the camera** — e.g. frames you copied
off the SD card. Requires Pillow + numpy (`pip install pillow numpy`).

---

## 🖥️ Monitoring & Quick-Switch HUD (`monitor_hud.py`)

A dark-mode on-screen overlay for framing and instant mode switching while
shooting — webcam/HDMI capture, a video file, or a folder of images/`.ARW`.
It never touches camera RAM itself: every real-hardware action is a plain
`opengate-rs.exe` subprocess call using that tool's own already-gated flags
(`--confirm-ram-write`, etc.) — the HUD invents no new write path.

```bash
# Demo mode: synthetic 3:2 test frame, simulated mode switching, no camera
python monitor_hud.py --demo

# Webcam / HDMI capture card as the monitor source
python monitor_hud.py --source 0 --exe host-injector/target/release/opengate-rs.exe

# A folder of frames (or .ARW files - shown via their embedded JPEG preview)
python monitor_hud.py --source ./frames
```

| Key | Does |
|---|---|
| `1` | Quick-Switch → Stock 16:9 (`3840x2160`). **No software restore exists** — this project is RAM-only by design; the real revert is a cold boot / battery pull (~10 s). `--demo` dry-runs `--plan` instead. |
| `2` | Quick-Switch → 4K Open Gate 3:2 (`3840x2560`). Live hardware needs an explicit in-HUD confirm before it will run `--confirm-ram-write`; `--demo` dry-runs `--plan`. |
| `3` | Quick-Switch → Live Ghosting / Multi-Exposure overlay (reuses `multi_exposure.py`'s blend modes) |
| `H` | toggle the Quick-Switch menu |
| `G` | cycle framing guides: **All** (3:2 + 16:9 + 9:16) → **16:9 only** → **9:16 only** → **Off** |
| `I` | toggle the top-right status pill (RAM state · active profile · `DEMO`/`LIVE USB`) |
| `W` | toggle the bottom-left luma waveform (0–100 IRE, off by default) |
| `M` | (mode 3) cycle the ghosting blend mode: `dark` → `bright` → `avg` → `add` |
| `Space` | (mode 3) freeze the current frame as the ghost reference |
| `Q` | quit |

**Framing guides** draw all three Open Gate crops at once by default: the full
3:2 frame, a 16:9 center crop (exactly `3840x2160` on the real sensor — the
stock resolution, letterboxed top/bottom with corner ticks), and a 9:16 center
crop (exactly `1440x2560`, pillarboxed left/right) for vertical Reels/Shorts
framing — all computed from whatever the live frame's actual size is, so the
same math holds in `--demo` at a smaller resolution too.

**Waveform** is a compact luma scope (BT.601, nearest-column sampled — good
enough to judge exposure at a glance, not a broadcast-grade tool) with a red
line at **94 IRE**, S-Log3's highlight clip point.

Needs OpenCV (`pip install opencv-python`); `.ARW` folder previews need `rawpy`
(same as `--live-ghost`, see above).

---

## 📱 Mobile RAM-only loading (no PC, on the go)

The session is **volatile** (gone at power-off), so loading it in the field is the
goal. Planned/experimental paths — **plug in ~2 s, unplug, shoot until power-off**:

- **Android (USB-C OTG):** run the Python tool via Termux, or a WebUSB page in
  Chrome — no app store needed.
- **iPhone (USB-C, 15/16):** a small companion app (built via GitHub Actions /
  sideload) drives the same USB sequence.
- **Pocket dongle (ESP32-S3 USB-C):** a stand-alone stick that replays the session
  when plugged — fully PC-free.

> These are on the roadmap; the desktop CLI is the reference today. See
> [`docs/ROADMAP.md`](docs/ROADMAP.en.md).

---

## 🎬 Post-processing (DaVinci Resolve / players)

Open Gate 3:2 clips may need a lossless container fix for some editors/players — no
re-encode, just remux:

```bash
ffmpeg -i input.mp4 -map 0:v:0 -map 0:a? -c copy -movflags +faststart output.mp4
```

### Vertical-correction + simultaneous 3:2 / 16:9 / 9:16 delivery

The **stable 3840×2560** clip uses the contributed sensor window (5952×**3876**),
which captures only `3876 / 3968 = 0.977` of the native 3:2 field — so the picture is
**~2.4 % too tall**. Correct it by squeezing height to **97.7 %**, then cut every
aspect you need from that one master:

```bash
# 0) One corrected 3:2 master (3840x2560 -> height x0.977), high-quality scaler
ffmpeg -i opengate.mp4 -vf "scale=3840:2502:flags=lanczos,setsar=1" \
       -c:v prores_ks -profile:v 3 -c:a copy master_3x2.mov

# 1) three deliverables from the corrected master, in ONE pass (no quality loss chain)
ffmpeg -i master_3x2.mov -filter_complex "\
  [0:v]crop=3840:2502[c32]; \
  [0:v]crop=3840:1408:0:(ih-1408)/2[c169]; \
  [0:v]crop=1408:2502:(iw-1408)/2:0[c916]" \
  -map "[c32]"  -c:v prores_ks -profile:v 3 deliver_3x2.mov \
  -map "[c169]" -c:v prores_ks -profile:v 3 deliver_16x9.mov \
  -map "[c916]" -c:v prores_ks -profile:v 3 deliver_9x16.mov
```

| Output | Crop from the 3840×2502 corrected master | Use |
|---|---|---|
| **3:2** | full frame `3840×2502` | the open-gate look, rear-LCD native |
| **16:9** | centre `3840×1408` (top/bottom trimmed) | standard video delivery |
| **9:16** | centre `1408×2502` | vertical / social, reframed from the taller capture |

> The whole point of open gate: shoot the 3:2 master **once**, then reframe 16:9 and
> 9:16 from the extra vertical resolution instead of re-shooting. The experimental
> true 3:2 window (5952×3968) removes the 97.7 % step — see
> [`RESEARCH.md`](RESEARCH.md).

---

## 🧬 Volatile RAM Open Gate 3:2 (research, `ram_opengate.py`)

Target: **ILCE-6700 firmware 2.00**, 3840×2160 → **3840×2560** in RAM only
(**gone on power-off / battery pull**). Open Gate is blocked at the app layer
(HAITA, `REC_MOVIE_ASPECT_RATIO_NOT_16_9` in `appFw.so`); this targets the downstream
encoder height word.

**How it really works (BIONZ XR).** Not a host-side memory poke. The verified pipeline
(as used by the [ArcaneLantern](https://github.com/ArcaneLantern/a6700-open-gate-test)
GPL kit — *referenced, never copied*) is: **Mass Storage** (`PID 0x0E76`) → Sony
**service mode** (re-enumerates `PID 0x0336`, via MIT [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE))
→ a small **on-camera ARM64 helper** is uploaded, run once, and *it* reads/writes the
camera's RAM, leaving a result file on the RAM disk.

> **This MIT build ships no on-camera helper** (a correct one embeds Sony
> firmware-derived tables; the vetted builds are GPL). So `ram_opengate.py` provides
> the MIT-clean **host side**: the verified 2.00 address map + dimensions, a read-only
> SCSI probe, an ARM64 signature scanner, and the verify/patch/restore logic driven
> through a pluggable `CameraMemory` transport. RAM read/write **refuses until a
> transport is wired** — it never guesses.

```bash
# No camera: print the verified 2.00 facts + the first command to run
python ram_opengate.py --info

# Read-only SCSI probe (switch the camera USB mode to Mass Storage first)
python ram_opengate.py --probe-msc

# Read-only (default): read + verify the encoder height sites
python ram_opengate.py --verify-only

# Opt-in volatile patch (0x0870 2160 -> 0x0A00 2560): checks stock first,
# backs up, writes, reads back. Needs a wired CameraMemory transport.
python ram_opengate.py --confirm-ram-write

# Revert in RAM without rebooting
python ram_opengate.py --restore
```

> ⚠️ **Unverified caveats (A6700 2.00).** The contributed 4K window makes the picture
> **~2.4 % too tall**; the **exact 3:2 window has never been run on an A6700** (expect a
> possible black frame / restart — a battery pull clears it); in-camera 3840×2560
> playback needs a separate fix. MIT code only, zero firmware bytes, zero flash writes.

### Single-session injector (`opengate_inject.py`) + declarative profiles

`ram_opengate.py` proves one site; `opengate_inject.py` applies a **whole profile in
one held service-mode session** — the camera is prodded into service mode once and
every step's writes are chained in RAM, removing the manual unplug/replug between
steps. The patch tables live as plain data in [`profiles/`](profiles/):

| Profile | Status | What |
|---|---|---|
| `profile_4k_24p_stable` | **verified** | 3840×2560 via the stable M19 chain (recorded clean) |
| `profile_true_3x2_experimental` | experimental | exact 5952×3968 window (never run) |
| `playback_fix` | experimental | optional R19 in-camera playback add-on |

Geometry words carry literal target bytes (arithmetic from the resolution);
firmware-derived encoder/sensor/playback blobs are **not in this repo** — each step
references a git-ignored `payloads/*.bin` verified by sha256. Preflight checks
NTSC/PAL vs the profile's frame rates and the STILL/MOVIE dial before any write.

```bash
# No camera: print the resolved write plan + preflight (default)
python opengate_inject.py profile_4k_24p_stable --video-standard NTSC --dial MOVIE

# List bundled profiles
python opengate_inject.py --list

# Read-only on hardware: confirm every site holds stock
python opengate_inject.py profile_4k_24p_stable --verify-only

# Opt-in apply (needs a wired CameraMemory transport; verify -> backup -> write -> readback)
python opengate_inject.py profile_4k_24p_stable --confirm-ram-write
```

See [`RESEARCH.md`](RESEARCH.md) for the hardware findings behind these profiles
(panels, L19-vs-M19 reboot, the 3980-row buffer that fits true 3:2).

**In the field (no laptop).** Once verified on PC, the volatile patch can run from a
phone over **USB-C OTG** (Android + Termux + `pyusb`/PMCA-RE for the host side). The
on-camera helper step still applies — the ArcaneLantern kit ships an Android APK that
performs it; this MIT tool covers the read-only probe/verify on the same phone.

---

## 🦀 Native rewrite — `host-injector/` (Rust) + `target-helper/` (Zig/C)

A native, dependency-light rewrite of the single-session injector, alongside the
Python tooling above (not a replacement yet — same `profiles/`, same clean-room rules):

- **[`host-injector/`](host-injector/README.md)** — Rust binary (`opengate-rs`)
  driving the USB side over [`rusb`](https://crates.io/crates/rusb): loads
  `profiles/*.json`, builds the OGP1 patch blob, and drives the one-session state
  machine (Mass Storage `054C:0E76` → service mode `054C:0336`) with the same
  verify-before-write, readback, and RAII rollback as the Python path.
- **[`target-helper/`](target-helper/README.md)** — the on-camera micro-helper, built
  freestanding for aarch64-linux-gnu with **Zig 0.17.1** (`zig build`, bundles the
  toolchain, no cross-gcc needed) or plain C99 (`make`, with
  `aarch64-linux-gnu-gcc`). Applies one OGP1 record at a time: verify stock → write
  64-byte-aligned line(s) → read back → cache flush.

### CLI workflow (`host-injector`)

```bash
cd host-injector
cargo run -- --list                                                    # list bundled profiles, no camera
cargo run -- profile_4k_24p_stable --video-standard NTSC --dial MOVIE  # --plan (default): write plan + preflight, no camera
cargo run -- profile_4k_24p_stable --verify-only                       # open the camera, confirm every site holds stock
cargo run -- profile_4k_24p_stable --confirm-ram-write                 # opt-in: apply the profile (volatile RAM)
cargo run -- --dump-ram 0x02580cd8 0x40 --out dump.bin                 # opt-in: dump LEN bytes from ADDR to a file
cargo run -- --scan-dump target_fw.bin --ref-profile profile_4k_24p_stable.json  # offline: no camera, see below
```

Entering Sony's service mode needs the Senser key tables — external MIT data, not
shipped in this repo (see [`host-injector/README.md`](host-injector/README.md)):

```bash
cargo run -- profile_4k_24p_stable --verify-only \
  --senser-config senser_blobs.json \   # {"sha1":[...],"sha256":[...]}, checked against cited fingerprints
  --allow-unverified-usb                # opt-in to send real vendor frames; asks to type "yes"
```

(`--senser-config` also reads from the `OG_SENSER_CONFIG` environment variable.)

**`VENDOR_PROTOCOL_VERIFIED` stays `false`** in `host-injector/src/pmca.rs`. The Senser
auth handshake and the real-hardware re-enumeration lifecycle (`StartSenser` →
re-enumerate as `054C:0336` → wire the senser transport) are implemented and
unit-tested against mocks, but **not yet proven on a live A6700**. Until that flag
flips to `true`, sending real vendor frames requires the explicit
`--allow-unverified-usb` opt-in above plus its interactive `yes` confirm — the same
two-gate pattern every real-hardware path in this repo uses.

---

## 🛰️ Contributing a New BIONZ XR Body

A **locked skeleton** profile already exists in [`profiles/`](profiles/) for each
body currently awaiting hardware (`fx30_v5.00`, `zve10m2_v1.00`, `fx2_v1.00`,
`fx3_v6.00`, `a7m4_v4.00`) — real step ids (`L13`/`L16`/`S16`), `"status":
"experimental"`, and **zero resolved writes**: no memory offset in this repo was
ever guessed. `host-injector` refuses `--confirm-ram-write` on a profile with
zero resolved writes, so these skeletons are safe to have around before anyone
has touched the body. If you have a camera from the table above and want to help
locate its sites, read-only, in three steps:

1. **`--dump-ram`** — once you're far enough to open a Senser-mode session on
   *your* body (same `--allow-unverified-usb` gate as everywhere else), read a
   candidate region to a local file:
   ```bash
   cargo run -- --dump-ram 0x02580cd8 0x40 --out your_body_dump.bin \
     --senser-config senser_blobs.json --allow-unverified-usb
   ```
2. **`--scan-dump`** — fully offline, no camera: search a firmware dump (yours,
   or a bigger one you already have) for the verified A6700 profile's stock-byte
   signatures (`L13`/`L16`/`S16`), and get a draft profile with whatever offsets
   it found:
   ```bash
   cargo run -- --scan-dump your_body_dump.bin --ref-profile profile_4k_24p_stable.json \
     --out your_body_draft.json
   ```
   A unique match becomes a write in the draft; an ambiguous or missing one is
   flagged in `notes` instead of guessed — resolve those by hand before trusting
   them.
3. **`--verify-only`** — merge the draft's resolved writes into your body's
   skeleton profile, then confirm every site actually holds the expected stock
   bytes **before** anyone tries `--confirm-ram-write`:
   ```bash
   cargo run -- your_body_v1.00 --verify-only --senser-config senser_blobs.json --allow-unverified-usb
   ```

Do **not** add an `L19`-equivalent step to a new body's profile: on the verified
A6700, `L19` (the high-speed-only encoder) rebooted the kernel on the
STILL→MOVIE switch (see [`RESEARCH.md`](RESEARCH.md)); `M19` was the stable
replacement there, and no non-A6700 body has an `M19` equivalent confirmed yet
either. Share results on the [Discord](https://discord.gg/Zr72h6AFa5) or open a
[GitHub Discussion](../../discussions) — see
[Community & ideas](#-community--ideas) below.

---

## 💬 Community & ideas

Ideas for features or for cameras to support are very welcome:

- **💡 Feature & camera requests** — open a
  [GitHub Issue](../../issues) or start a
  [GitHub Discussion](../../discussions). Tell us your body, firmware version and
  what you'd like to see (e.g. "add A7 IV support", "test Open Gate on FX30").
- **🗨️ Community Discord** — join **Sony Alpha OpenLab** to coordinate testing and
  share results: **https://discord.gg/Zr72h6AFa5**

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

---

## 📚 Documentation

- [`RESEARCH.md`](RESEARCH.md) — **original A6700 2.00 hardware findings**: display
  panels (rear 3:2 / EVF 4:3), the L19-vs-M19 kernel-reboot diagnosis, and the
  3980-row `dmmwb` buffer calculation that opens the true 3:2 window.
- [`profiles/README.md`](profiles/README.md) — declarative Open Gate patch-table format.
- [`host-injector/README.md`](host-injector/README.md) / [`target-helper/README.md`](target-helper/README.md)
  — native Rust/Zig rewrite of the single-session injector (host + on-camera helper).
- [`docs/ROADMAP.en.md`](docs/ROADMAP.en.md) (EN) / [`docs/ROADMAP.md`](docs/ROADMAP.md) (FR)
  — milestones done and next steps (portability, Open Gate study, more bodies).
- [`docs/RESULTS.en.md`](docs/RESULTS.en.md) (EN) / [`docs/RESULTS.md`](docs/RESULTS.md) (FR)
  — **experimental results** validated live on the A6700 (multi-exposure success,
  HAITA 3:2 lock).
- [`docs/PROTOCOL.en.md`](docs/PROTOCOL.en.md) (EN) / [`docs/PROTOCOL.md`](docs/PROTOCOL.md) (FR)
  — PTP / "SDIO" protocol architecture.
- [`docs/BIONZ_XR_PTP_SDIO.md`](docs/BIONZ_XR_PTP_SDIO.md) — why the legacy
  BIONZ X Senser path stalls on BIONZ XR, the verified PTP/SDIO v300 handshake
  and `0x9209` property-record format, and the `sdio_probe.py` read-only
  decoder (`--dump-bin` / `--parse-bin` / `--json`).
- [`docs/DEVICE_PROPERTIES.en.md`](docs/DEVICE_PROPERTIES.en.md) (EN) /
  [`docs/DEVICE_PROPERTIES.md`](docs/DEVICE_PROPERTIES.md) (FR)
  — full table of the **386** `DevicePropCode` / control codes.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) (EN) / [`CONTRIBUTING.fr.md`](CONTRIBUTING.fr.md) (FR)
  — contribution rules (including the strict ban on firmware content and the
  read-only-first policy).

## 📁 Repository layout

```
Sony-Open-Gate-Lab/
├── cameras/             # 14 BIONZ XR body profiles (USB identity) + cameras.py loader
├── probe_a6700.py       # read-only USB diagnostic probe
├── sdio_probe.py        # read-only 0x9209 SDIO v300 decoder (dump/parse/json)
├── scripts/
│   └── probe_a6700_sdio.py  # CLI entrypoint for sdio_probe.py
├── experiment_a6700.py  # session-only write experiments (opt-in, --confirm-session-write)
├── multi_exposure.py    # automated multi-exposure capture + optional stacking
├── monitor_hud.py       # dark-mode monitoring/quick-switch HUD (framing guides, waveform)
├── ram_opengate.py      # volatile RAM Open Gate helper (Mass Storage, research)
├── opengate_inject.py   # single-session Open Gate injector (loads profiles/)
├── host-injector/       # native rewrite, host side (Rust + rusb) + README
├── target-helper/       # native rewrite, on-camera helper (Zig 0.17.1 / C99) + README
├── profiles/            # declarative Open Gate patch tables (JSON) + format README
├── sony_codes.py        # generated PTP code dictionaries (protocol constants)
├── requirements.txt   # Python dependencies (pyusb; pillow/numpy/OpenCV optional)
├── .gitignore         # strict exclusion of firmware binaries + raw dumps
├── LICENSE            # MIT license
├── RESEARCH.md        # original A6700 2.00 hardware findings
├── CONTRIBUTING.md / CONTRIBUTING.fr.md   # contribution guide (EN / FR)
├── docs/
│   ├── PROTOCOL.en.md / PROTOCOL.md              # protocol architecture (EN / FR)
│   ├── DEVICE_PROPERTIES.en.md / .md             # 386-code table (EN / FR)
│   ├── RESULTS.en.md / RESULTS.md                # live experimental results (EN / FR)
│   ├── BIONZ_XR_PTP_SDIO.md                      # PTP/SDIO v300 handshake + 0x9209 format
│   ├── ROADMAP.en.md / ROADMAP.md                # milestones & next steps (EN / FR)
│   └── proofs/                                   # anonymized log extracts + proof screenshots
└── README.md / README.fr.md                      # this file (EN / FR)
```

## 🖼️ Media & samples

- **Before / after:** _(screenshots coming soon)_
- **Sample files:** _(Google Drive link — TBA)_
- **Community Discord:** [Sony Alpha OpenLab](https://discord.gg/Zr72h6AFa5)

---

## 🙏 Acknowledgements

- **[ArcaneLantern/a6700-open-gate-test](https://github.com/ArcaneLantern/a6700-open-gate-test)**
  (GPL-3.0) — upstream Open Gate research for the A6700. Its service-mode pipeline and
  address map were the reference for our RAM path. *Referenced, never copied:* this
  MIT repo contains no GPL source and no firmware bytes; our profiles were built
  clean-room from our own read-only hardware dumps.
- **[ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)** (MIT) — the Sony
  service-mode handshake.
- **Claude Code (Anthropic)** strongly assisted in the research, reverse-engineering
  analysis, and development of this project — firmware static analysis, PTP/SDIO
  protocol mapping, and the Python tooling.

---

## License

Distributed under the **MIT** license (see [LICENSE](LICENSE)). Original code only;
no component or file from the Sony firmware is included.
