# A6700-Remote-Tools

**🌍 Language: English · [Français](README.fr.md)**

**Read-only diagnostic** tools for the USB dialogue (PTP / Sony "SDIO") with a
**Sony A6700 (ILCE-6700)** body.

This repository exists to explore the camera's remote-control protocol in a **safe,
non-destructive** way: open a session, read device information and extended property
descriptors. No write, setting, or trigger command is ever issued.

> ⚠️ **Independent, unofficial project.** Not affiliated with Sony. Use at your own
> risk, for interoperability and personal study only.

---

## 🎯 Project scope

This project has a **scope strictly limited to two research goals**, and performs
**no permanent modification** of the camera:

1. **Open Gate 3:2** — investigating the feasibility of recording video in the full
   3:2 sensor aspect ratio ("open gate").
2. **Multi-exposure** — investigating multi-frame capture mechanisms.

Both goals are approached through **static analysis** and **read-only USB
diagnostics**. This repository is **not** intended to provide a general control tool,
a shutter/record trigger, or any persistent modification of the camera's settings or
firmware. Any future feature stays bounded to these two goals and to the
"no permanent writes" principle.

---

## 🔒 Safety scope

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

# Force a specific USB PID
python probe_a6700.py --pid 0x0DE7
```

### Expected output (example)

```
=== probe_a6700: READ-ONLY USB diagnostic ===

[+] PTP device opened (VID 0x054C PID 0x0DE7, interface #0).

[1] OpenSession(0x1002)          -> OK
[2] GetDeviceInfo(0x1001)        -> OK (512 bytes)
      Manufacturer     : Sony Corporation
      Model            : ILCE-6700
      Firmware version : 1.00
      Serial number    : xxxxxxxx
      Vendor extension : id=0x11 "Sony PTP Extensions"
      Operations       : 42 (vendor 0x92xx: 30)
      Properties       : 7
[3] SDIO_Connect(0x9201) ph1     -> OK
[3] SDIO_Connect(0x9201) ph2     -> OK
[4] SDIO_GetExtDeviceInfo(0x9202)-> OK (900 bytes)
[5] GetExtDevicePropDesc still_capture_mode (drive mode) -> OK (40 bytes)
[5] GetExtDevicePropDesc aspect_ratio                    -> OK (28 bytes)
[5] GetExtDevicePropDesc file_format_movie               -> OK (36 bytes)

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

## 📚 Documentation

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
├── probe_a6700.py     # read-only USB diagnostic probe
├── requirements.txt   # Python dependencies (pyusb)
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
