# A6700-Remote-Tools

**🌍 Language: English · [Français](README.fr.md)**

An **open-source toolkit for Sony Alpha cameras**, developed and tested first on the
**Sony A6700 (ILCE-6700)**, with an architecture designed to extend to other Sony
bodies over time.

Today the toolkit provides **read-only diagnostics** for the USB dialogue
(PTP / Sony "SDIO"): open a session, read device information and extended property
descriptors. No write, setting, or trigger command is issued.

> ⚠️ **Independent, unofficial project.** Not affiliated with Sony. Use at your own
> risk, for interoperability and personal study only.
>
> 🚧 **Active development.** This project is actively developed and updated
> regularly — expect frequent changes while the architecture matures.

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
extension), which is largely shared across the line. Support is rolled out by
processor generation:

| Generation | Bodies | Planned support |
|---|---|---|
| **BIONZ XR** (APS-C) | **A6700** ✅, **FX30** | **Direct / priority** — primary development target |
| **BIONZ XR** (Full-Frame) | A7 IV, A7C II, … | Direct (after APS-C validation) |
| **BIONZ X** (APS-C) | A6600, A6400 | Later support (older protocol dialect) |
| Other APS-C | ZV-E10 II | Planned |

Development priority:

1. **Sony A6700** — reference body (developed and tested here first).
2. Other **BIONZ XR APS-C** bodies (FX30) — expected to be the closest match.
3. **Full-Frame BIONZ XR** (A7 IV, A7C II…).
4. **BIONZ X** bodies (A6400, A6600) — handled afterward, as their protocol
   generation differs.

> ✅ = actively tested · others = planned. Compatibility is validated per body;
> a code being present in the protocol does not mean it is exposed on every model.
> Want your body supported? See [Community & ideas](#-community--ideas).

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
controlled interval** and can optionally **stack** them locally (average = classic
multi-exposure blend, or lighten = star-trail style). It also requires
`--confirm-session-write` and takes real pictures.

```powershell
# 5 frames, 1s apart (AF before each shot)
python multi_exposure.py --confirm-session-write --shots 5 --interval 1.0

# Continuous/bracket drive mode, no AF, auto-download each frame (0xFFFFC001) and
# stack them into a single multi-exposure image
python multi_exposure.py --confirm-session-write --shots 8 --no-af --drive-value 0x2 \
    --download-dir out/ --stack out/multi.png --stack-mode average

# OFFLINE: stack a folder (no camera, no --confirm-session-write needed)
python multi_exposure.py --stack-dir ./frames --stack trails.png --stack-mode lighten
```

| Option | Purpose |
|---|---|
| `--shots N` / `--interval S` | capture N frames, S seconds apart |
| `--no-af` | skip the S1 (AF) half-press; S2 full-press only |
| `--drive-value V` | set `still_capture_mode` (0x5013) first (continuous/bracket enum value) |
| `--download-dir DIR` | auto-download each frame via the Sony PC-save handle `0xFFFFC001` (read-only `GetObject`) |
| `--stack OUT` / `--stack-dir DIR` / `--stack-mode` | stack images (`average` or `lighten`) |

**Auto-download (PC Remote).** In PC Remote mode the A6700 doesn't expose
`GetObjectHandles`; it places the last captured image on the special Sony handle
**`0xFFFFC001`**, which `--download-dir` reads after each shot via `GetObject`. Set the
camera's **Save Destination to "PC+Camera" or "PC only"** for this to work.

**Offline stacking.** `--stack-dir DIR --stack OUT` (without `--confirm-session-write`)
stacks images from a folder **without touching the camera** — e.g. frames you copied
off the SD card. Requires Pillow + numpy (`pip install pillow numpy`).

---

## 💬 Community & ideas

Ideas for features or for cameras to support are very welcome:

- **💡 Feature & camera requests** — open a
  [GitHub Issue](../../issues) or start a
  [GitHub Discussion](../../discussions). Tell us your body, firmware version and
  what you'd like to see (e.g. "add A7 IV support", "test Open Gate on FX30").
- **🗨️ Community Discord** — *coming soon.* A community server is planned to
  coordinate testing and share results.
  `🔗 Discord invite: TBA` *(placeholder — link will be added here)*

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

---

## 📚 Documentation

- [`docs/ROADMAP.en.md`](docs/ROADMAP.en.md) (EN) / [`docs/ROADMAP.md`](docs/ROADMAP.md) (FR)
  — milestones done and next steps (portability, Open Gate study, more bodies).
- [`docs/RESULTS.en.md`](docs/RESULTS.en.md) (EN) / [`docs/RESULTS.md`](docs/RESULTS.md) (FR)
  — **experimental results** validated live on the A6700 (multi-exposure success,
  HAITA 3:2 lock).
- [`docs/PROTOCOL.en.md`](docs/PROTOCOL.en.md) (EN) / [`docs/PROTOCOL.md`](docs/PROTOCOL.md) (FR)
  — PTP / "SDIO" protocol architecture.
- [`docs/DEVICE_PROPERTIES.en.md`](docs/DEVICE_PROPERTIES.en.md) (EN) /
  [`docs/DEVICE_PROPERTIES.md`](docs/DEVICE_PROPERTIES.md) (FR)
  — full table of the **386** `DevicePropCode` / control codes.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) (EN) / [`CONTRIBUTING.fr.md`](CONTRIBUTING.fr.md) (FR)
  — contribution rules (including the strict ban on firmware content and the
  read-only-first policy).

## 📁 Repository layout

```
A6700-Remote-Tools/
├── probe_a6700.py       # read-only USB diagnostic probe
├── experiment_a6700.py  # session-only write experiments (opt-in, --confirm-session-write)
├── multi_exposure.py    # automated multi-exposure capture + optional stacking
├── sony_codes.py        # generated PTP code dictionaries (protocol constants)
├── requirements.txt   # Python dependencies (pyusb; pillow/numpy optional)
├── .gitignore         # strict exclusion of firmware binaries
├── LICENSE            # MIT license
├── CONTRIBUTING.md / CONTRIBUTING.fr.md   # contribution guide (EN / FR)
├── docs/
│   ├── PROTOCOL.en.md / PROTOCOL.md              # protocol architecture (EN / FR)
│   └── DEVICE_PROPERTIES.en.md / .md             # 386-code table (EN / FR)
└── README.md / README.fr.md                      # this file (EN / FR)
```

## License

Distributed under the **MIT** license (see [LICENSE](LICENSE)). Original code only;
no component or file from the Sony firmware is included.
