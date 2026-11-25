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
(read-only GetObject) and stack them locally (average = classic multi-exposure,
or lighten = star-trail style).

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

# Standard PTP read-only object ops (for optional image download).
OP_GET_OBJECT_HANDLES = 0x1007
OP_GET_OBJECT_INFO = 0x1008
OP_GET_OBJECT = 0x1009


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


def capture_sequence(dev, shots: int, interval: float, af: bool):
    print(f"[shoot ] {shots} frame(s), interval {interval:.2f}s, AF={'on' if af else 'off'}")
    for i in range(1, shots + 1):
        capture_one(dev, af=af)
        print(f"         frame {i}/{shots} triggered")
        if i < shots:
            time.sleep(interval)
    print("[shoot ] sequence complete")


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

def stack_images(paths, out_path, mode="average"):
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("[stack ] Pillow/numpy not installed -> skipping stacking "
              "(pip install pillow numpy). Stack the files manually if needed.")
        return False
    if not paths:
        print("[stack ] no images to stack.")
        return False

    acc = None
    n = 0
    base_size = None
    for p in paths:
        try:
            im = Image.open(p).convert("RGB")
        except Exception as e:  # noqa: BLE001
            print(f"[stack ] skip {p}: {e}")
            continue
        if base_size is None:
            base_size = im.size
        elif im.size != base_size:
            print(f"[stack ] size mismatch for {p} ({im.size} vs {base_size}); skip.")
            continue
        arr = np.asarray(im, dtype=np.float64)
        if acc is None:
            acc = np.zeros_like(arr) if mode == "average" else arr.copy()
        if mode == "average":
            acc += arr
            n += 1
        elif mode == "lighten":
            acc = np.maximum(acc, arr)
        else:
            print(f"[stack ] unknown mode {mode}")
            return False
    if acc is None:
        print("[stack ] no usable images.")
        return False
    if mode == "average":
        acc /= max(n, 1)
    from PIL import Image as _Image
    _Image.fromarray(acc.clip(0, 255).astype("uint8")).save(out_path)
    print(f"[stack ] {mode} of {n if mode=='average' else len(paths)} image(s) "
          f"-> {out_path}")
    return True


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
                    help="After capture, pull the NEW objects over PTP into this "
                         "directory (read-only GetObject; best-effort).")
    ap.add_argument("--stack", default=None, metavar="OUT.png",
                    help="Stack images into this output file.")
    ap.add_argument("--stack-dir", default=None,
                    help="Directory of images to stack (defaults to --download-dir).")
    ap.add_argument("--stack-mode", choices=("average", "lighten"),
                    default="average",
                    help="average = multi-exposure blend; lighten = max (star trails).")
    args = ap.parse_args()

    if not args.confirm_session_write:
        sys.exit("[REFUSED] This script triggers REAL captures on the camera.\n"
                 "Re-run with --confirm-session-write to acknowledge. For read-only\n"
                 "diagnostics use probe_a6700.py instead.")
    if args.shots < 1:
        sys.exit("[INFO] --shots must be >= 1.")

    allowed = set(READ_ONLY_OPS)
    allowed.update({OP_SDIO_SET_EXT_DEVICE_PROP_VALUE, OP_SDIO_CONTROL_DEVICE,
                    OP_GET_OBJECT_HANDLES, OP_GET_OBJECT_INFO, OP_GET_OBJECT})
    if args.sdk_handshake:
        allowed.add(OP_SDIO_SET_REMOTE_SDK_INFO)

    print("=== multi_exposure: SESSION-ONLY automated capture ===")
    dev = None
    try:
        dev = connect(args.pid, allowed, sdk_handshake=args.sdk_handshake)
        if args.drive_value is not None:
            set_drive_mode(dev, args.drive_value)
            time.sleep(0.2)

        before = list_object_handles(dev) if args.download_dir else None

        capture_sequence(dev, args.shots, args.interval, af=not args.no_af)
        time.sleep(0.5)

        downloaded = []
        if args.download_dir:
            after = list_object_handles(dev)
            if before is None or after is None:
                print("[dl    ] object enumeration unavailable over PTP here; "
                      "copy the files from the SD card instead.")
            else:
                new = after - before
                print(f"[dl    ] {len(new)} new object(s) detected.")
                downloaded = download_objects(dev, new, args.download_dir)

        if args.stack:
            src_dir = args.stack_dir or args.download_dir
            if downloaded:
                paths = downloaded
            elif src_dir and os.path.isdir(src_dir):
                paths = sorted(glob.glob(os.path.join(src_dir, "*")))
            else:
                paths = []
                print("[stack ] no source images (use --download-dir or --stack-dir).")
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
