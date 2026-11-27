#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi_exposure.py - Automated multi-exposure capture for the Sony A6700.

⚠️  THIS SCRIPT TRIGGERS THE CAMERA (session-only, volatile control).
    It takes real pictures. Use `probe_a6700.py` for read-only diagnostics.

What it does (all validated live on A6700 fw 2.00)
--------------------------------------------------
Using only the confirmed session-only control commands:
  - optional drive / bracket mode set via still_capture_mode (0x5013),
  - controlled shutter via ControlDevice(0x9207): S1 (0xD2C1) + S2 (0xD2C2),
it captures N frames at a controlled interval (multi-frame / multi-exposure
sequence). It can then optionally pull the newly captured images over PTP
(read-only GetObject) and stack them locally with the four Fujifilm
multi-exposure modes (additive, average, bright/lighten, dark/darken) plus a
screen blend - all computed in float32 linear space (--stack-all renders all
four core modes at once).

Nothing is written to the camera's persistent storage or firmware; the only
camera-side effects are the captures themselves and volatile session state.
Requires the explicit flag --confirm-session-write.

Stacking needs Pillow (+ numpy): `pip install pillow numpy`. If they are missing,
capture still works and you can stack the files from the SD card yourself.

Project scope: multi-exposure research (and, separately, Open Gate - which is
blocked at the application layer, see README). Read CONTRIBUTING.md.
"""

from __future__ import annotations

import argparse
import glob
import io
import os
import struct
import sys
import time

try:
    import usb.core
except ImportError:  # pragma: no cover
    sys.exit("[ERROR] pyusb is missing. Install it with: pip install pyusb")

from probe_a6700 import (
    PtpUsbDevice, PtpError, rc_str, PTP_RC_OK, READ_ONLY_OPS,
    OP_OPEN_SESSION, OP_CLOSE_SESSION, OP_SDIO_CONNECT,
    OP_SDIO_GET_EXT_DEVICE_INFO, OP_SDIO_GET_ALL_EXT_DEVICE_PROP_INFO,
    OP_SDIO_SET_REMOTE_SDK_INFO, OP_SDIO_SET_EXT_DEVICE_PROP_VALUE,
    OP_SDIO_CONTROL_DEVICE,
)

# Codes (validated live)
PROP_STILL_CAPTURE_MODE = 0x5013
CTRL_S1_BUTTON = 0xD2C1
CTRL_S2_BUTTON = 0xD2C2

# ControlDevice button values: 2 = press (down), 1 = release (up). Best-effort.
BTN_PRESS = 0x0002
BTN_RELEASE = 0x0001

# Verbose poll diagnostics (set from --verbose in main).
VERBOSE = False

# Standard PTP read-only object ops (for optional image download).
OP_GET_OBJECT_HANDLES = 0x1007
OP_GET_OBJECT_INFO = 0x1008
OP_GET_OBJECT = 0x1009

# SDIO_SetContentsTransferMode (session write): routes captured contents to the PC
# handle (0xFFFFC001) with the "disclose contents" flag, independent of the camera's
# Save Destination menu. param1 = transfer mode, param2 = disclose-contents flag.
OP_SDIO_SET_CONTENTS_TRANSFER_MODE = 0x9212

# In PC Remote mode the A6700 does not expose GetObjectHandles; it instead places
# the last captured image on this special Sony "PC save" object handle, readable
# via GetObjectInfo / GetObject. Requires "Save Destination: PC+Camera" or "PC only"
# on the camera.
SONY_PC_SAVE_HANDLE = 0xFFFFC001
# Live View stream object handle (read repeatedly via GetObject for a live preview).
SONY_LIVEVIEW_HANDLE = 0xFFFFC002


def _u16(v: int) -> bytes:
    return struct.pack("<H", v & 0xFFFF)


# ---------------------------------------------------------------------------
# Camera control (session-only)
# ---------------------------------------------------------------------------

def connect(pid, allowed, sdk_handshake=False) -> PtpUsbDevice:
    dev = PtpUsbDevice.open_first(pid=pid, allowed_ops=allowed)
    print(f"[+] PTP device opened (VID 0x{dev.dev.idVendor:04X} "
          f"PID 0x{dev.dev.idProduct:04X}, interface #{dev.intf.bInterfaceNumber}).")
    rc, _ = dev.transaction(OP_OPEN_SESSION, params=[1])
    print(f"    OpenSession            -> {rc_str(rc)}")
    if rc != PTP_RC_OK:
        raise PtpError("could not open session")
    for phase in (1, 2):
        dev.transaction(OP_SDIO_CONNECT, params=[phase, 0, 0])
        time.sleep(0.05)
    if sdk_handshake:
        dev.transaction(OP_SDIO_SET_REMOTE_SDK_INFO, params=[0x012C],
                        send_data=struct.pack("<I", 0x0000012C))
    dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x012C])
    dev.transaction(OP_SDIO_CONNECT, params=[3, 0, 0])
    print("    SDIO connect handshake -> done")
    return dev


def enable_pc_content_transfer(dev, mode=1, disclose=1):
    """Send SetContentsTransferMode (0x9212) to route captured images to the PC
    handle (0xFFFFC001) with 'disclose contents', so downloads work even if the
    camera's Save Destination menu is left on 'Camera only'. Session-only; value
    semantics are best-effort (param1=mode 1/2, param2=disclose)."""
    try:
        rc, _ = dev.transaction(OP_SDIO_SET_CONTENTS_TRANSFER_MODE,
                                params=[mode, disclose, 0])
    except PtpError as e:
        print(f"[xfer  ] SetContentsTransferMode(0x9212) not sent: {e}")
        return
    print(f"[xfer  ] SetContentsTransferMode(0x9212) mode={mode} disclose={disclose} "
          f"-> {rc_str(rc)}")


def set_drive_mode(dev, value: int):
    print(f"[drive ] SetExtDevicePropValue(0x5013 still_capture_mode) <- {value}")
    rc, _ = dev.transaction(OP_SDIO_SET_EXT_DEVICE_PROP_VALUE,
                            params=[PROP_STILL_CAPTURE_MODE], send_data=_u16(value))
    print(f"         response -> {rc_str(rc)}")


def capture_one(dev, af=True, af_delay=0.4, hold=0.12):
    """One controlled shot: (S1 AF) -> S2 press/release -> (S1 release)."""
    if af:
        dev.transaction(OP_SDIO_CONTROL_DEVICE, params=[CTRL_S1_BUTTON],
                        send_data=_u16(BTN_PRESS))
        time.sleep(af_delay)
    dev.transaction(OP_SDIO_CONTROL_DEVICE, params=[CTRL_S2_BUTTON],
                    send_data=_u16(BTN_PRESS))
    time.sleep(hold)
    dev.transaction(OP_SDIO_CONTROL_DEVICE, params=[CTRL_S2_BUTTON],
                    send_data=_u16(BTN_RELEASE))
    if af:
        dev.transaction(OP_SDIO_CONTROL_DEVICE, params=[CTRL_S1_BUTTON],
                        send_data=_u16(BTN_RELEASE))


def parse_objectinfo(data: bytes):
    """Parse a PTP ObjectInfo dataset. Returns {format, size, filename}."""
    try:
        fmt = struct.unpack_from("<H", data, 4)[0]
        size = struct.unpack_from("<I", data, 8)[0]
        fname = ""
        if len(data) > 56:  # Filename PTP string starts at offset 56
            n = data[56]
            if n:
                fname = data[57:57 + n * 2].decode("utf-16-le", "replace").rstrip("\x00")
        return {"format": fmt, "size": size, "filename": fname}
    except (struct.error, IndexError):
        return {"format": 0, "size": 0, "filename": ""}


def _ext_for(fname, fmt, data):
    """Pick a file extension from the ObjectInfo filename/format, then the bytes."""
    if fname and "." in fname:
        return "." + fname.rsplit(".", 1)[1].lower()
    if fmt == 0x3801 or data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):  # TIFF/Sony ARW container
        return ".arw"
    return ".bin"


def fetch_pc_save_object(dev, out_dir, index, retries=12, delay=0.25):
    """After a capture in PC Remote mode, pull the image the camera placed on the
    special Sony PC-save handle (0xFFFFC001).

    BIONZ XR: the body does not prepare/size the object until GetObjectInfo(0x1008)
    is queried, so each poll calls GetObjectInfo first and only fetches once its
    ObjectCompressedSize > 0. The file may be JPEG or RAW (.ARW), so the extension
    comes from ObjectInfo (filename/format), not just the FF D8 magic."""
    for attempt in range(1, retries + 1):
        try:
            rc_i, info = dev.transaction(OP_GET_OBJECT_INFO, params=[SONY_PC_SAVE_HANDLE])
        except PtpError:
            rc_i, info = None, b""
        oi = parse_objectinfo(info) if (rc_i == PTP_RC_OK and info) else \
            {"format": 0, "size": 0, "filename": ""}
        if VERBOSE:
            print(f"         poll {attempt:2d}: GetObjectInfo rc={rc_str(rc_i) if rc_i is not None else 'ERR'} "
                  f"size={oi['size']} fmt=0x{oi['format']:04X} name={oi['filename']!r}")
        if rc_i == PTP_RC_OK and oi["size"] > 0:
            try:
                rc_o, data = dev.transaction(OP_GET_OBJECT, params=[SONY_PC_SAVE_HANDLE])
            except PtpError:
                rc_o, data = None, b""
            if VERBOSE:
                print(f"         poll {attempt:2d}: GetObject     "
                      f"rc={rc_str(rc_o) if rc_o is not None else 'ERR'} bytes={len(data)}")
            if rc_o == PTP_RC_OK and data:
                os.makedirs(out_dir, exist_ok=True)
                ext = _ext_for(oi["filename"], oi["format"], data)
                path = os.path.join(out_dir, f"frame_{index:03d}{ext}")
                with open(path, "wb") as f:
                    f.write(data)
                print(f"         saved frame {index} -> {path} "
                      f"({len(data)} bytes, after {attempt} poll(s))")
                return path
        time.sleep(delay)
    print(f"         (image not ready on 0xFFFFC001 after {retries} polls; "
          "try --verbose, --xfer-mode 2, or Save Destination = PC)")
    return None


def capture_sequence(dev, shots: int, interval: float, af: bool, download_dir=None):
    print(f"[shoot ] {shots} frame(s), interval {interval:.2f}s, AF={'on' if af else 'off'}")
    if download_dir:
        print("         (auto-download via Sony handle 0xFFFFC001 - set the camera's "
              "'Save Destination' to 'PC+Camera' or 'PC only')")
    saved = []
    for i in range(1, shots + 1):
        capture_one(dev, af=af)
        print(f"         frame {i}/{shots} triggered")
        if download_dir:
            time.sleep(0.4)  # let the body publish the image on 0xFFFFC001
            p = fetch_pc_save_object(dev, download_dir, i)
            if p:
                saved.append(p)
            else:
                print("         (no image on 0xFFFFC001 - check Save Destination)")
        if i < shots:
            time.sleep(interval)
    print("[shoot ] sequence complete")
    return saved


# ---------------------------------------------------------------------------
# Optional read-only image download over PTP
# ---------------------------------------------------------------------------

def list_object_handles(dev):
    """Return the set of object handles via GetObjectHandles (read-only)."""
    try:
        rc, data = dev.transaction(OP_GET_OBJECT_HANDLES,
                                   params=[0xFFFFFFFF, 0x00000000, 0x00000000])
    except PtpError:
        return None
    if rc != PTP_RC_OK or len(data) < 4:
        return None
    count = struct.unpack_from("<I", data, 0)[0]
    if 4 + count * 4 > len(data):
        return None
    return set(struct.unpack_from("<%dI" % count, data, 4))


def download_objects(dev, handles, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for h in sorted(handles):
        try:
            rc, data = dev.transaction(OP_GET_OBJECT, params=[h])
        except PtpError:
            continue
        if rc != PTP_RC_OK or not data:
            continue
        ext = ".jpg" if data[:2] == b"\xff\xd8" else ".bin"
        path = os.path.join(out_dir, f"obj_{h:08X}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        saved.append(path)
        print(f"         downloaded handle 0x{h:08X} -> {path} ({len(data)} bytes)")
    return saved


# ---------------------------------------------------------------------------
# Local stacking
# ---------------------------------------------------------------------------

# Fujifilm Multi-Exposure modes. Aliases resolve to the canonical name.
MODE_ALIASES = {"lighten": "bright", "darken": "dark"}
CORE_MODES = ("additive", "average", "bright", "dark")   # the 4 Fujifilm modes
ALL_MODES = ("additive", "average", "bright", "dark", "screen")


def _norm_mode(mode):
    """Resolve an alias (lighten->bright, darken->dark) to the canonical name."""
    return MODE_ALIASES.get(mode, mode)


def _load_frame(path):
    """Load one frame as a float32 HxWx3 array + its white level (max value).
    Handles 8-bit JPEG/PNG, 16-bit PNG/TIFF, and (if rawpy is installed) RAW.
    Returns (None, None) when the frame can't be decoded."""
    from PIL import Image
    import numpy as np
    ext = os.path.splitext(path)[1].lower()
    if ext in (".arw", ".dng", ".nef", ".cr2", ".cr3", ".raf", ".rw2"):
        try:
            import rawpy
        except ImportError:
            print(f"[stack ] skip RAW {os.path.basename(path)} "
                  "(install rawpy to decode RAW: pip install rawpy).")
            return None, None
        with rawpy.imread(path) as raw:
            rgb16 = raw.postprocess(output_bps=16, no_auto_bright=True,
                                    use_camera_wb=True)
        return np.asarray(rgb16, dtype=np.float32), 65535.0
    im = Image.open(path)
    if im.mode in ("I", "I;16", "I;16B", "I;16L", "F"):   # 16-bit / float images
        arr = np.asarray(im, dtype=np.float32)
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        return arr, 65535.0
    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    return arr, 255.0


def _load_frames(paths):
    """Load frames into a common float32 range. If any frame is 16-bit, 8-bit
    frames are scaled up to the 16-bit range so the math stays linear and free of
    shadow banding. Returns (frames, max_val, base_size)."""
    frames, maxes, base_size = [], [], None
    for p in paths:
        try:
            arr, mv = _load_frame(p)
        except Exception as e:  # noqa: BLE001
            print(f"[stack ] skip {p}: {e}")
            continue
        if arr is None:
            continue
        size = (arr.shape[1], arr.shape[0])
        if base_size is None:
            base_size = size
        elif size != base_size:
            print(f"[stack ] size mismatch for {p} ({size} vs {base_size}); skip.")
            continue
        frames.append(arr)
        maxes.append(mv)
    if not frames:
        return [], 255.0, None
    max_val = max(maxes)
    for i, mv in enumerate(maxes):      # unify 8-bit frames up to 16-bit range
        if mv != max_val:
            frames[i] = frames[i] * (max_val / mv)
    return frames, max_val, base_size


def _blend(frames, mode, max_val):
    """Blend a list of float32 HxWx3 frames by `mode`, in float32 linear space."""
    import numpy as np
    mode = _norm_mode(mode)
    stack = np.stack(frames, axis=0)       # (N, H, W, 3), float32
    n = stack.shape[0]
    if mode == "additive":                 # film-style additive exposure
        out = np.clip(stack.sum(axis=0), 0.0, max_val)
    elif mode == "average":                # balanced exposure mean
        out = stack.sum(axis=0) / float(n)
    elif mode == "bright":                 # per-pixel max (light trails, stars)
        out = np.maximum.reduce(stack)
    elif mode == "dark":                   # per-pixel min (silhouettes)
        out = np.minimum.reduce(stack)
    elif mode == "screen":                 # 1-(1-A)(1-B), soft double-exposure
        inv = max_val - stack
        prod = inv[0].copy()
        for k in range(1, n):
            prod *= inv[k] / max_val
        out = max_val - prod
    else:
        raise ValueError(f"unknown stack mode: {mode}")
    return out


def _save_result(arr, max_val, out_path):
    """Save a float32 result. 16-bit TIFF when the extension asks for it and the
    source was 16-bit (needs tifffile); otherwise 8-bit PNG/JPEG."""
    from PIL import Image
    import numpy as np
    ext = os.path.splitext(out_path)[1].lower()
    if ext in (".tif", ".tiff") and max_val > 255:
        out16 = np.clip(arr / max_val * 65535.0, 0, 65535).astype("uint16")
        try:
            import tifffile
            tifffile.imwrite(out_path, out16)
            return
        except ImportError:
            print("[stack ] 16-bit TIFF needs tifffile; saving 8-bit instead.")
    out8 = np.clip(arr / max_val * 255.0, 0, 255).astype("uint8")
    Image.fromarray(out8).save(out_path)


def _warn_additive_ev(n):
    """Additive stacking of N frames adds ~+log2(N) EV; remind to compensate."""
    import math
    ev = math.log2(n) if n > 0 else 0.0
    print(f"[stack ] additive: {n} frames add about +{ev:.1f} EV of brightness. "
          f"Set NEGATIVE exposure compensation (~-{ev:.1f} EV total) on the camera "
          "or the highlights will clip.")


def stack_images(paths, out_path, mode="average"):
    try:
        import numpy as np  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[stack ] Pillow/numpy not installed -> skipping stacking "
              "(pip install pillow numpy). Stack the files manually if needed.")
        return False
    if not paths:
        print("[stack ] no images to stack.")
        return False
    canon = _norm_mode(mode)
    if canon not in ALL_MODES:
        print(f"[stack ] unknown mode {mode}")
        return False
    frames, max_val, _ = _load_frames(paths)
    if not frames:
        print("[stack ] no usable images.")
        return False
    if canon == "additive":
        _warn_additive_ev(len(frames))
    out = _blend(frames, canon, max_val)
    _save_result(out, max_val, out_path)
    print(f"[stack ] {canon} of {len(frames)} image(s) -> {out_path}")
    return True


def stack_all_modes(paths, base_out):
    """Render all 4 core Fujifilm modes from the SAME frames into
    <stem>_additive / _average / _bright / _dark.<ext>. Returns output paths."""
    try:
        import numpy as np  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        print("[stack ] Pillow/numpy not installed -> cannot --stack-all.")
        return []
    frames, max_val, _ = _load_frames(paths)
    if not frames:
        print("[stack ] no usable images to --stack-all.")
        return []
    stem, ext = os.path.splitext(base_out or "multi_exposure.png")
    ext = ext or ".png"
    outs = []
    for m in CORE_MODES:
        if m == "additive":
            _warn_additive_ev(len(frames))
        out = _blend(frames, m, max_val)
        op = f"{stem}_{m}{ext}"
        _save_result(out, max_val, op)
        print(f"[stack ] {m} of {len(frames)} image(s) -> {op}")
        outs.append(op)
    return outs


# ---------------------------------------------------------------------------
# 16-bit linear RAW multi-exposure blending (.ARW / rawpy), 2..9 frames.
#
# Separate from stack_images()/_blend() above on purpose: those decode RAW via
# rawpy's default gamma-encoded postprocess() (right for a quick preview, not
# for additive math), then blend in that gamma space. Physically correct
# multi-exposure math - summing or averaging light - needs to happen in LINEAR
# light, before any display gamma curve, or midtones come out wrong (gamma-space
# averaging is not the same as averaging the light itself). This path decodes
# with gamma=(1, 1) (no curve) + no_auto_bright, blends in that linear space,
# and writes a 16-bit TIFF so no precision is lost to an 8-bit intermediate.
# ---------------------------------------------------------------------------
RAW_BLEND_MODES = ("dark", "bright", "avg", "add")
RAW_BLEND_MIN_FRAMES = 2
RAW_BLEND_MAX_FRAMES = 9


def blend_raw16(frames, mode):
    """Blend 2..9 same-shape uint16 arrays into one uint16 array, in linear light.

    mode:
      'dark'   - per-pixel minimum (silhouettes against a bright background)
      'bright' - per-pixel maximum (light trails, star trails)
      'avg'    - per-pixel mean, rounded (balanced exposure, noise averaging)
      'add'    - per-pixel sum, clamped to 65535 (film-style additive exposure;
                 the physically correct way to combine N frames shot at
                 correspondingly lower exposure so the sum reconstructs one
                 properly-exposed frame)

    Pure numpy math, no file I/O - independently unit-testable on synthetic
    arrays without rawpy or a real RAW file.
    """
    import numpy as np

    n = len(frames)
    if not (RAW_BLEND_MIN_FRAMES <= n <= RAW_BLEND_MAX_FRAMES):
        raise ValueError(
            f"blend_raw16: need {RAW_BLEND_MIN_FRAMES}..{RAW_BLEND_MAX_FRAMES} "
            f"frames, got {n}"
        )
    if mode not in RAW_BLEND_MODES:
        raise ValueError(f"blend_raw16: unknown mode {mode!r}, want one of {RAW_BLEND_MODES}")
    shape0 = frames[0].shape
    for f in frames:
        if f.shape != shape0:
            raise ValueError(f"blend_raw16: frame shape mismatch {f.shape} != {shape0}")

    stack = np.stack(frames, axis=0).astype(np.float64)  # (N, H, W[, C]), linear
    if mode == "dark":
        out = stack.min(axis=0)
    elif mode == "bright":
        out = stack.max(axis=0)
    elif mode == "avg":
        out = stack.mean(axis=0)
    else:  # "add"
        out = stack.sum(axis=0)
    return np.clip(np.rint(out), 0, 65535).astype(np.uint16)


def load_raw16_linear(path):
    """Decode one RAW file to a linear (no gamma curve, no auto-brightness)
    16-bit RGB array via rawpy - safe to add/average/min/max pixel-wise across
    frames. Raises RuntimeError if rawpy isn't installed."""
    import numpy as np
    try:
        import rawpy
    except ImportError as e:
        raise RuntimeError("RAW multi-exposure needs rawpy (pip install rawpy).") from e
    with rawpy.imread(path) as raw:
        rgb16 = raw.postprocess(
            output_bps=16,
            no_auto_bright=True,
            use_camera_wb=True,
            gamma=(1, 1),  # linear output, no display tone curve
        )
    return np.asarray(rgb16, dtype=np.uint16)


def save_tiff16(arr, out_path):
    """Save a uint16 array as a 16-bit TIFF. Raises RuntimeError if tifffile
    isn't installed."""
    import numpy as np
    try:
        import tifffile
    except ImportError as e:
        raise RuntimeError("16-bit TIFF export needs tifffile (pip install tifffile).") from e
    tifffile.imwrite(out_path, np.asarray(arr, dtype=np.uint16))


def blend_raw_files(paths, out_path, mode="avg"):
    """End to end: decode 2..9 RAW files to linear 16-bit, blend by `mode`
    (dark/bright/avg/add), write a 16-bit TIFF. Returns True on success, False
    (with a printed reason) otherwise - never raises for a missing optional
    dependency or a bad argument."""
    n = len(paths)
    if not (RAW_BLEND_MIN_FRAMES <= n <= RAW_BLEND_MAX_FRAMES):
        print(f"[raw-blend] need {RAW_BLEND_MIN_FRAMES}..{RAW_BLEND_MAX_FRAMES} "
              f"RAW files, got {n}.")
        return False
    if mode not in RAW_BLEND_MODES:
        print(f"[raw-blend] unknown mode {mode!r}, want one of {RAW_BLEND_MODES}.")
        return False
    try:
        frames = [load_raw16_linear(p) for p in paths]
    except RuntimeError as e:
        print(f"[raw-blend] {e}")
        return False
    try:
        out = blend_raw16(frames, mode)
    except ValueError as e:
        print(f"[raw-blend] {e}")
        return False
    try:
        save_tiff16(out, out_path)
    except RuntimeError as e:
        print(f"[raw-blend] {e}")
        return False
    print(f"[raw-blend] {mode} of {len(frames)} RAW frame(s) -> {out_path}")
    return True


def _write_preview(paths, download_dir):
    """Write a quick average preview of the frames captured so far (for composition
    during interactive shooting). Best-effort; silent without Pillow/numpy."""
    try:
        import numpy as np  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return
    frames, max_val, _ = _load_frames(paths)
    if not frames:
        return
    out = _blend(frames, "average", max_val)
    prev = os.path.join(download_dir, "_preview.png")
    try:
        _save_result(out, max_val, prev)
        print(f"         preview -> {prev}")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Live View + interactive double-exposure
# ---------------------------------------------------------------------------

def fetch_liveview(dev):
    """Read one Live View frame from the Sony live-view handle (0xFFFFC002) and
    return it as a PIL RGB image, or None. Read-only.

    BIONZ XR: like the PC-save handle, the body prepares/sizes the live-view
    object only once GetObjectInfo(0x1008) is queried, so query it first and
    skip the frame until ObjectCompressedSize > 0 (matches fetch_pc_save_object)."""
    try:
        rc_i, info = dev.transaction(OP_GET_OBJECT_INFO, params=[SONY_LIVEVIEW_HANDLE])
    except PtpError:
        return None
    if rc_i != PTP_RC_OK or not info or parse_objectinfo(info)["size"] <= 0:
        return None
    try:
        rc, data = dev.transaction(OP_GET_OBJECT, params=[SONY_LIVEVIEW_HANDLE])
    except PtpError:
        return None
    if rc != PTP_RC_OK or not data:
        return None
    i = data.find(b"\xff\xd8")  # skip any Sony header, find the JPEG SOI
    if i < 0:
        return None
    try:
        from PIL import Image
        return Image.open(io.BytesIO(data[i:])).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def interactive_capture(dev, shots, af, download_dir, out_path, stack_mode,
                        stack_all=False):
    """Fujifilm-style step-by-step multi-exposure. Capture frame 1, then before
    each next frame wait for a key:
      [Enter] shoot next frame | [r] retake last frame | [q] finish & stack now.
    After each shot a running average preview is written to the download dir so
    you can judge composition. Frames are stacked at the end (or --stack-all)."""
    download_dir = download_dir or "me_frames"
    os.makedirs(download_dir, exist_ok=True)
    out_path = out_path or "multi_exposure.png"
    saved = []

    def _shoot(idx):
        print(f"[inter ] capturing frame {idx}/{shots}...")
        capture_one(dev, af=af)
        time.sleep(0.4)
        return fetch_pc_save_object(dev, download_dir, idx)

    p = _shoot(1)
    if p:
        saved.append(p)
        _write_preview(saved, download_dir)
    else:
        print("         (no image on 0xFFFFC001 - check Save Destination)")

    while len(saved) < shots:
        nxt = len(saved) + 1
        try:
            choice = input(f"[inter ] frame {len(saved)}/{shots} saved. "
                           "[Enter]=shoot next  [r]=retake last  [q]=finish: "
                           ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[inter ] stopped by user.")
            break
        if choice == "q":
            break
        if choice == "r":
            if saved:
                print("[inter ] retaking last frame...")
                rp = _shoot(len(saved))
                if rp:
                    saved[-1] = rp
                    _write_preview(saved, download_dir)
            continue
        np_path = _shoot(nxt)
        if np_path:
            saved.append(np_path)
            _write_preview(saved, download_dir)
        else:
            print("         (no image on 0xFFFFC001 - check Save Destination)")

    if len(saved) >= 2:
        if stack_all:
            stack_all_modes(saved, out_path)
        else:
            stack_images(saved, out_path, mode=stack_mode)
    else:
        print("[inter ] need >= 2 downloaded frames to stack.")
    return saved


def live_overlay(dev, shots, af, download_dir, out_path, opacity, blend,
                 stack_all=False):
    """Capture frame 1, then open a light tkinter window showing the live Sony feed
    (0xFFFFC002) blended over frame 1 in real time, so you can align the next frame.
    Space triggers the next capture; Esc/q quits. Final stack uses `blend`."""
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        import numpy as np
    except ImportError:
        print("[live  ] --live-overlay needs tkinter + Pillow + numpy "
              "(pip install pillow numpy; tkinter ships with Python).")
        return []

    download_dir = download_dir or "me_frames"
    os.makedirs(download_dir, exist_ok=True)
    out_path = out_path or "multi_exposure.png"

    print(f"[live  ] capturing frame 1/{shots} (base)...")
    capture_one(dev, af=af)
    time.sleep(0.4)
    base_path = fetch_pc_save_object(dev, download_dir, 1)
    if not base_path:
        print("[live  ] no base image on 0xFFFFC001 (check Save Destination).")
        return []
    base = Image.open(base_path).convert("RGB")
    # Downscale the preview for responsiveness (keep the full-res file for stacking).
    pw = min(960, base.width)
    ph = int(base.height * pw / base.width)
    base_small = base.resize((pw, ph))
    base_arr = np.asarray(base_small, dtype=np.float64)

    state = {"saved": [base_path], "shot": 2, "busy": False}

    root = tk.Tk()
    root.title("A6700 live double-exposure - Space=capture, Esc=quit")
    label = tk.Label(root)
    label.pack()
    status = tk.Label(root, text="Align the next subject, then press Space.")
    status.pack()

    mode = _norm_mode(blend)

    def blend_preview(lv):
        lv = lv.resize((pw, ph))
        b = (np.asarray(lv, dtype=np.float64) * float(opacity)).clip(0, 255)
        if mode == "screen":
            out = 255.0 - (255.0 - base_arr) * (255.0 - b) / 255.0
        elif mode == "dark":
            out = np.minimum(base_arr, b)
        elif mode == "additive":
            out = base_arr + b
        elif mode == "average":
            out = (base_arr + b) / 2.0
        else:  # bright (per-pixel max) - default live preview
            out = np.maximum(base_arr, b)
        return Image.fromarray(out.clip(0, 255).astype("uint8"))

    def refresh():
        if not root.winfo_exists():
            return
        lv = fetch_liveview(dev)
        if lv is not None:
            img = ImageTk.PhotoImage(blend_preview(lv))
            label.config(image=img)
            label.image = img
        else:
            status.config(text="Waiting for Live View (0xFFFFC002)...")
        root.after(120, refresh)

    def do_capture(_=None):
        if state["busy"] or state["shot"] > shots:
            return
        state["busy"] = True
        status.config(text=f"Capturing frame {state['shot']}/{shots}...")
        root.update_idletasks()
        capture_one(dev, af=af)
        time.sleep(0.4)
        p = fetch_pc_save_object(dev, download_dir, state["shot"])
        if p:
            state["saved"].append(p)
        state["shot"] += 1
        state["busy"] = False
        if state["shot"] > shots:
            root.destroy()
        else:
            status.config(text=f"Align subject {state['shot']}, press Space.")

    root.bind("<space>", do_capture)
    root.bind("<Escape>", lambda e: root.destroy())
    root.bind("q", lambda e: root.destroy())
    # Closing the window (title-bar X) should quit cleanly, not raise on the
    # pending root.after() callback.
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.after(200, refresh)
    root.mainloop()

    if len(state["saved"]) >= 2:
        if stack_all:
            stack_all_modes(state["saved"], out_path)
        else:
            stack_images(state["saved"], out_path, mode=blend)
    else:
        print("[live  ] need >= 2 frames to stack.")
    return state["saved"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Automated multi-exposure capture for the Sony A6700 "
                    "(session-only control; takes real pictures)."
    )
    ap.add_argument("--confirm-session-write", action="store_true",
                    help="REQUIRED. Acknowledge this triggers real captures.")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None,
                    help="Explicit USB PID (e.g. 0x0E78). Default: auto.")
    ap.add_argument("--sdk-handshake", action="store_true",
                    help="Also send SetRemoteSdkInfo (0x9214) during connect.")
    ap.add_argument("--shots", type=int, default=3,
                    help="Number of frames to capture (default 3).")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Seconds between frames (default 1.0).")
    ap.add_argument("--no-af", action="store_true",
                    help="Skip the S1 (AF) half-press; S2 full-press only.")
    ap.add_argument("--drive-value", type=lambda x: int(x, 0), default=None,
                    help="Optional value to write into still_capture_mode (0x5013) "
                         "first (e.g. a continuous/bracket enum value from probe [5]).")
    ap.add_argument("--download-dir", default=None,
                    help="Auto-download each captured frame via the Sony PC-save "
                         "handle 0xFFFFC001 into this directory (read-only GetObject). "
                         "Set the camera's 'Save Destination' to 'PC+Camera' or 'PC only'.")
    ap.add_argument("--stack", default=None, metavar="OUT.png",
                    help="Stack images into this output file.")
    ap.add_argument("--stack-dir", default=None,
                    help="Directory of images to stack (defaults to --download-dir).")
    ap.add_argument("--stack-mode",
                    choices=("additive", "average", "bright", "lighten",
                             "dark", "darken", "screen"),
                    default="average",
                    help="Fujifilm multi-exposure blend: additive = film-style sum "
                         "(clipped; add negative EV); average = mean (classic); "
                         "bright/lighten = per-pixel max (star trails, bright subjects); "
                         "dark/darken = per-pixel min (silhouettes); "
                         "screen = 1-(1-A)(1-B) (soft double-exposure look).")
    ap.add_argument("--stack-all", action="store_true",
                    help="Render ALL 4 core Fujifilm modes from the same frames into "
                         "<stem>_additive/_average/_bright/_dark so you can compare.")
    ap.add_argument("--interactive", "--manual-step", action="store_true",
                    dest="interactive",
                    help="Fujifilm step-by-step: shoot frame 1, then per frame choose "
                         "[Enter] shoot next / [r] retake last / [q] finish & stack.")
    ap.add_argument("--live-overlay", action="store_true",
                    help="Open a window showing the live feed (0xFFFFC002) blended "
                         "over frame 1 in real time; Space captures. Needs tkinter+Pillow.")
    ap.add_argument("--overlay-opacity", type=float, default=0.5,
                    help="Live-overlay opacity of the live feed over frame 1 (0..1).")
    ap.add_argument("--no-pc-transfer", action="store_true",
                    help="Do NOT send SetContentsTransferMode (0x9212) during connect "
                         "(by default it is sent when downloading, to route images to "
                         "0xFFFFC001 regardless of the Save Destination menu).")
    ap.add_argument("--xfer-mode", type=int, choices=(1, 2), default=1,
                    help="param1 for SetContentsTransferMode (0x9212); try 2 if 1 "
                         "does not route images to 0xFFFFC001 (default 1).")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print per-poll GetObjectInfo/GetObject response codes and "
                         "sizes when fetching from 0xFFFFC001.")
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.verbose

    # Offline stacking: --stack-dir without a capture does NOT touch the camera, so
    # it runs directly, no --confirm-session-write needed.
    if not args.confirm_session_write:
        if args.stack_dir and (args.stack or args.stack_all):
            print("=== multi_exposure: OFFLINE stacking (no camera) ===")
            paths = sorted(glob.glob(os.path.join(args.stack_dir, "*")))
            if not paths:
                sys.exit(f"[INFO] no images found in {args.stack_dir}")
            if args.stack_all:
                outs = stack_all_modes(paths, args.stack)
                sys.exit(0 if outs else 1)
            ok = stack_images(paths, args.stack, mode=args.stack_mode)
            sys.exit(0 if ok else 1)
        sys.exit("[REFUSED] Capturing triggers REAL pictures on the camera.\n"
                 "Re-run with --confirm-session-write to acknowledge, or run offline\n"
                 "stacking only with --stack-dir DIR --stack OUT (no camera, no flag).\n"
                 "For read-only diagnostics use probe_a6700.py instead.")
    if args.shots < 1:
        sys.exit("[INFO] --shots must be >= 1.")

    allowed = set(READ_ONLY_OPS)
    allowed.update({OP_SDIO_SET_EXT_DEVICE_PROP_VALUE, OP_SDIO_CONTROL_DEVICE,
                    OP_GET_OBJECT_HANDLES, OP_GET_OBJECT_INFO, OP_GET_OBJECT,
                    OP_SDIO_SET_CONTENTS_TRANSFER_MODE})
    if args.sdk_handshake:
        allowed.add(OP_SDIO_SET_REMOTE_SDK_INFO)

    print("=== multi_exposure: SESSION-ONLY automated capture ===")
    dev = None
    try:
        dev = connect(args.pid, allowed, sdk_handshake=args.sdk_handshake)
        # Route captured images to the PC handle (0xFFFFC001) whenever we download,
        # unless disabled. Avoids "no image" when Save Destination = Camera only.
        needs_download = (args.download_dir or args.interactive or args.live_overlay)
        if needs_download and not args.no_pc_transfer:
            enable_pc_content_transfer(dev, mode=args.xfer_mode)
            time.sleep(0.2)
        if args.drive_value is not None:
            set_drive_mode(dev, args.drive_value)
            time.sleep(0.2)

        if args.live_overlay:
            # Real-time Live View overlay over frame 1; Space captures the rest.
            live_overlay(dev, args.shots, af=not args.no_af,
                         download_dir=args.download_dir, out_path=args.stack,
                         opacity=args.overlay_opacity, blend=args.stack_mode,
                         stack_all=args.stack_all)
        elif args.interactive:
            # Step-by-step double exposure with a reframe pause between frames.
            interactive_capture(dev, args.shots, af=not args.no_af,
                                download_dir=args.download_dir, out_path=args.stack,
                                stack_mode=args.stack_mode, stack_all=args.stack_all)
        else:
            # Timed sequence, auto-downloading each frame from 0xFFFFC001.
            downloaded = capture_sequence(dev, args.shots, args.interval,
                                          af=not args.no_af,
                                          download_dir=args.download_dir)
            time.sleep(0.3)
            if args.stack or args.stack_all:
                src_dir = args.stack_dir or args.download_dir
                if downloaded:
                    paths = downloaded
                elif src_dir and os.path.isdir(src_dir):
                    paths = sorted(glob.glob(os.path.join(src_dir, "*")))
                else:
                    paths = []
                    print("[stack ] no source images (use --download-dir/--stack-dir).")
                if args.stack_all:
                    stack_all_modes(paths, args.stack)
                else:
                    stack_images(paths, args.stack, mode=args.stack_mode)

    except PtpError as e:
        sys.exit(f"[ERROR] {e}")
    except usb.core.USBError as e:
        sys.exit(f"[USB ERROR] {e}\n"
                 "On Windows: install the WinUSB driver via Zadig (see README.md).")
    finally:
        if dev is not None:
            try:
                dev.transaction(OP_CLOSE_SESSION)
                print("\n[+] CloseSession -> session closed (control was session-only).")
            except PtpError:
                pass
            dev.close()


if __name__ == "__main__":
    main()
