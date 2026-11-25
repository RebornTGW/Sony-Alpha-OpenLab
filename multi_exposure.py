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

# Standard PTP read-only object ops (for optional image download).
OP_GET_OBJECT_HANDLES = 0x1007
OP_GET_OBJECT_INFO = 0x1008
OP_GET_OBJECT = 0x1009

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


def fetch_pc_save_object(dev, out_dir, index):
    """After a capture in PC Remote mode, pull the image the camera placed on the
    special Sony PC-save handle (0xFFFFC001). Read-only GetObject; returns the saved
    path or None."""
    try:
        rc, data = dev.transaction(OP_GET_OBJECT, params=[SONY_PC_SAVE_HANDLE])
    except PtpError:
        return None
    if rc != PTP_RC_OK or not data:
        return None
    os.makedirs(out_dir, exist_ok=True)
    ext = ".jpg" if data[:2] == b"\xff\xd8" else ".bin"
    path = os.path.join(out_dir, f"frame_{index:03d}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    print(f"         saved frame {index} -> {path} ({len(data)} bytes)")
    return path


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
            if mode != "average":
                n += 1
                continue
        if mode == "average":
            acc += arr
            n += 1
        elif mode == "lighten":
            acc = np.maximum(acc, arr)
            n += 1
        elif mode == "screen":
            # screen: 1 - (1-A)*(1-B); classic double-exposure blend (Fuji/Canon).
            acc = 255.0 - (255.0 - acc) * (255.0 - arr) / 255.0
            n += 1
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
    print(f"[stack ] {mode} of {n} image(s) -> {out_path}")
    return True


# ---------------------------------------------------------------------------
# Live View + interactive double-exposure
# ---------------------------------------------------------------------------

def fetch_liveview(dev):
    """Read one Live View frame from the Sony live-view handle (0xFFFFC002) and
    return it as a PIL RGB image, or None. Read-only GetObject."""
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


def interactive_capture(dev, shots, af, download_dir, out_path, stack_mode):
    """Step-by-step double exposure: capture frame 1, then wait for the user to
    reframe before each next frame, then stack immediately."""
    download_dir = download_dir or "me_frames"
    os.makedirs(download_dir, exist_ok=True)
    out_path = out_path or "multi_exposure.png"
    saved = []
    for i in range(1, shots + 1):
        if i == 1:
            print(f"[inter ] capturing frame 1/{shots} (base)...")
        else:
            try:
                input(f"[inter ] reframe the next subject, then press Enter to "
                      f"capture frame {i}/{shots} (Ctrl+C to stop)...")
            except (EOFError, KeyboardInterrupt):
                print("\n[inter ] stopped by user.")
                break
        capture_one(dev, af=af)
        time.sleep(0.4)
        p = fetch_pc_save_object(dev, download_dir, i)
        if p:
            saved.append(p)
        else:
            print("         (no image on 0xFFFFC001 - check Save Destination)")
    if len(saved) >= 2:
        stack_images(saved, out_path, mode=stack_mode)
    else:
        print("[inter ] need >= 2 downloaded frames to stack.")
    return saved


def live_overlay(dev, shots, af, download_dir, out_path, opacity, blend):
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

    def blend_preview(lv):
        lv = lv.resize((pw, ph))
        b = (np.asarray(lv, dtype=np.float64) * float(opacity)).clip(0, 255)
        if blend == "screen":
            out = 255.0 - (255.0 - base_arr) * (255.0 - b) / 255.0
        else:  # lighten
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
    root.after(200, refresh)
    root.mainloop()

    if len(state["saved"]) >= 2:
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
    ap.add_argument("--stack-mode", choices=("average", "lighten", "screen"),
                    default="average",
                    help="average = multi-exposure blend; lighten = max (star trails); "
                         "screen = 1-(1-A)(1-B) (Fuji/Canon double-exposure look).")
    ap.add_argument("--interactive", action="store_true",
                    help="Step-by-step: capture frame 1, wait for Enter to reframe "
                         "before each next frame, then stack immediately.")
    ap.add_argument("--live-overlay", action="store_true",
                    help="Open a window showing the live feed (0xFFFFC002) blended "
                         "over frame 1 in real time; Space captures. Needs tkinter+Pillow.")
    ap.add_argument("--overlay-opacity", type=float, default=0.5,
                    help="Live-overlay opacity of the live feed over frame 1 (0..1).")
    args = ap.parse_args()

    # Offline stacking: --stack-dir without a capture does NOT touch the camera, so
    # it runs directly, no --confirm-session-write needed.
    if not args.confirm_session_write:
        if args.stack_dir and args.stack:
            print("=== multi_exposure: OFFLINE stacking (no camera) ===")
            paths = sorted(glob.glob(os.path.join(args.stack_dir, "*")))
            if not paths:
                sys.exit(f"[INFO] no images found in {args.stack_dir}")
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

        if args.live_overlay:
            # Real-time Live View overlay over frame 1; Space captures the rest.
            live_overlay(dev, args.shots, af=not args.no_af,
                         download_dir=args.download_dir, out_path=args.stack,
                         opacity=args.overlay_opacity, blend=args.stack_mode)
        elif args.interactive:
            # Step-by-step double exposure with a reframe pause between frames.
            interactive_capture(dev, args.shots, af=not args.no_af,
                                download_dir=args.download_dir, out_path=args.stack,
                                stack_mode=args.stack_mode)
        else:
            # Timed sequence, auto-downloading each frame from 0xFFFFC001.
            downloaded = capture_sequence(dev, args.shots, args.interval,
                                          af=not args.no_af,
                                          download_dir=args.download_dir)
            time.sleep(0.3)
            if args.stack:
                src_dir = args.stack_dir or args.download_dir
                if downloaded:
                    paths = downloaded
                elif src_dir and os.path.isdir(src_dir):
                    paths = sorted(glob.glob(os.path.join(src_dir, "*")))
                else:
                    paths = []
                    print("[stack ] no source images (use --download-dir/--stack-dir).")
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
