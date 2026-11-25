#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiment_a6700.py - CONTROLLED, SESSION-ONLY experiments for the Sony A6700.

⚠️  THIS SCRIPT WRITES TO THE CAMERA (session-only, volatile).
    It is NOT the read-only probe. Use `probe_a6700.py` for diagnostics.

Scope and safety
----------------
This script performs ONLY non-persistent, session-scoped operations over USB.
Everything it changes lives in the camera's RAM for the current USB session and
is erased on reboot / battery removal. It writes NOTHING to persistent storage,
settings files, or firmware.

It must be run with the explicit flag `--confirm-session-write`; without it, the
script refuses to do anything. Each experiment prints the PTP response code so you
can see exactly what the camera accepted or rejected.

Experiments (opt-in, one at a time):
  --test-aspect-3-2     Try to set aspect_ratio (0xD211) to 1 (3:2) in Video mode
                        via SetExtDevicePropValue (0x9205), then read it back.
  --test-burst-trigger  Optionally set still_capture_mode (0x5013) via
                        --drive-value, then run a controlled ControlDevice (0x9207)
                        sequence: S1 (0xD2C1) press/release + S2 (0xD2C2)
                        press/release, to validate multi-frame triggering.

Project scope: Open Gate 3:2 and multi-exposure research only. Read
CONTRIBUTING.md. The S1/S2 control values and the SDK handshake payload are
best-effort and may need adjustment per body/firmware.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    import usb.core
except ImportError:  # pragma: no cover
    sys.exit("[ERROR] pyusb is missing. Install it with: pip install pyusb")

from probe_a6700 import (
    PtpUsbDevice, PtpError, rc_str, prop_name, decode_prop_value,
    PTP_RC_OK, READ_ONLY_OPS,
    OP_OPEN_SESSION, OP_CLOSE_SESSION, OP_SDIO_CONNECT,
    OP_SDIO_GET_EXT_DEVICE_INFO, OP_SDIO_GET_EXT_DEVICE_PROP_VALUE,
    OP_SDIO_SET_REMOTE_SDK_INFO, OP_SDIO_SET_EXT_DEVICE_PROP_VALUE,
    OP_SDIO_CONTROL_DEVICE,
)

# DevicePropCode / ControlDevice codes used here
PROP_ASPECT_RATIO = 0xD211
PROP_STILL_CAPTURE_MODE = 0x5013
CTRL_S1_BUTTON = 0xD2C1
CTRL_S2_BUTTON = 0xD2C2

# ControlDevice button values. Convention: 2 = press (down), 1 = release (up).
# Best-effort; swap if your body behaves differently.
BTN_PRESS = 0x0002
BTN_RELEASE = 0x0001


def _u16(v: int) -> bytes:
    return struct.pack("<H", v & 0xFFFF)


def open_and_connect(pid, allowed, sdk_handshake=False) -> PtpUsbDevice:
    """Open the camera, run the standard SDIO connect handshake, return the device.
    `allowed` is the explicit opcode set this session may send."""
    dev = PtpUsbDevice.open_first(pid=pid, allowed_ops=allowed)
    print(f"[+] PTP device opened (VID 0x{dev.dev.idVendor:04X} "
          f"PID 0x{dev.dev.idProduct:04X}, interface #{dev.intf.bInterfaceNumber}).")

    rc, _ = dev.transaction(OP_OPEN_SESSION, params=[1])
    print(f"    OpenSession(0x1002)        -> {rc_str(rc)}")
    if rc != PTP_RC_OK:
        raise PtpError("could not open session")

    for phase in (1, 2):
        rc, _ = dev.transaction(OP_SDIO_CONNECT, params=[phase, 0, 0])
        print(f"    SDIO_Connect ph{phase}          -> {rc_str(rc)}")
        time.sleep(0.05)

    if sdk_handshake:
        rc, _ = dev.transaction(OP_SDIO_SET_REMOTE_SDK_INFO, params=[0x012C],
                                send_data=struct.pack("<I", 0x0000012C))
        print(f"    SDIO_SetRemoteSdkInfo      -> {rc_str(rc)} (session-only)")

    rc, _ = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x012C])
    print(f"    SDIO_GetExtDeviceInfo      -> {rc_str(rc)}")
    rc, _ = dev.transaction(OP_SDIO_CONNECT, params=[3, 0, 0])
    print(f"    SDIO_Connect ph3           -> {rc_str(rc)}")
    return dev


def read_value(dev, code):
    rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_PROP_VALUE, params=[code])
    return rc, data


def test_aspect_3_2(dev):
    print("\n=== test-aspect-3-2 (session-only write) ===")
    rc, data = read_value(dev, PROP_ASPECT_RATIO)
    print(f"[before] GetExtDevicePropValue(0xD211) -> {rc_str(rc)}")
    if rc == PTP_RC_OK:
        decode_prop_value(PROP_ASPECT_RATIO, data)

    print("[write ] SetExtDevicePropValue(0xD211) <- 1 (3:2)")
    rc, _ = dev.transaction(OP_SDIO_SET_EXT_DEVICE_PROP_VALUE,
                            params=[PROP_ASPECT_RATIO], send_data=_u16(1))
    print(f"         response -> {rc_str(rc)}"
          + ("  (accepted)" if rc == PTP_RC_OK else "  (rejected/blocked)"))

    time.sleep(0.2)
    rc, data = read_value(dev, PROP_ASPECT_RATIO)
    print(f"[after ] GetExtDevicePropValue(0xD211) -> {rc_str(rc)}")
    if rc == PTP_RC_OK:
        decode_prop_value(PROP_ASPECT_RATIO, data)
    print("Interpretation: value 1 = 3:2, 2 = 16:9. If 'after' is still 2, the "
          "body refused 3:2 in movie mode (expected per the HAITA capability gate).")


def test_burst_trigger(dev, drive_value):
    print("\n=== test-burst-trigger (session-only write) ===")
    if drive_value is not None:
        print(f"[write ] SetExtDevicePropValue(0x5013 still_capture_mode) "
              f"<- {drive_value}")
        rc, _ = dev.transaction(OP_SDIO_SET_EXT_DEVICE_PROP_VALUE,
                                params=[PROP_STILL_CAPTURE_MODE],
                                send_data=_u16(drive_value))
        print(f"         response -> {rc_str(rc)}")
        time.sleep(0.2)
    else:
        print("[info  ] no --drive-value given; leaving drive mode unchanged.")

    seq = [
        ("S1 press  (0xD2C1)", CTRL_S1_BUTTON, BTN_PRESS),
        ("S2 press  (0xD2C2)", CTRL_S2_BUTTON, BTN_PRESS),
        ("S2 release(0xD2C2)", CTRL_S2_BUTTON, BTN_RELEASE),
        ("S1 release(0xD2C1)", CTRL_S1_BUTTON, BTN_RELEASE),
    ]
    for label, ctrl, val in seq:
        rc, _ = dev.transaction(OP_SDIO_CONTROL_DEVICE, params=[ctrl],
                                send_data=_u16(val))
        print(f"[ctrl  ] {label} <- {val}  -> {rc_str(rc)}")
        time.sleep(0.15)
    print("Done. Check the camera: a frame (or a burst/bracket, depending on the "
          "drive mode) should have been captured.")


def main():
    ap = argparse.ArgumentParser(
        description="Controlled SESSION-ONLY experiments for the Sony A6700 "
                    "(writes volatile, erased on reboot). NOT read-only."
    )
    ap.add_argument("--confirm-session-write", action="store_true",
                    help="REQUIRED. Acknowledge that this performs session-only "
                         "writes to the camera.")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None,
                    help="Explicit USB PID (e.g. 0x0E78). Default: auto.")
    ap.add_argument("--sdk-handshake", action="store_true",
                    help="Also send SetRemoteSdkInfo (0x9214) during connect.")
    ap.add_argument("--test-aspect-3-2", action="store_true",
                    help="Try to set aspect_ratio (0xD211) to 3:2 and read back.")
    ap.add_argument("--test-burst-trigger", action="store_true",
                    help="Run an S1/S2 ControlDevice trigger sequence.")
    ap.add_argument("--drive-value", type=lambda x: int(x, 0), default=None,
                    help="Optional value to write into still_capture_mode (0x5013) "
                         "before --test-burst-trigger (enum value from probe [5]).")
    args = ap.parse_args()

    if not args.confirm_session_write:
        sys.exit("[REFUSED] This script performs session-only WRITES to the camera.\n"
                 "Re-run with --confirm-session-write to acknowledge, plus one of\n"
                 "--test-aspect-3-2 / --test-burst-trigger. For diagnostics only,\n"
                 "use the strictly read-only probe_a6700.py instead.")
    if not (args.test_aspect_3_2 or args.test_burst_trigger):
        sys.exit("[INFO] Nothing to do. Choose --test-aspect-3-2 and/or "
                 "--test-burst-trigger.")

    # Explicit allow-list for this session: read ops + the specific writes needed.
    allowed = set(READ_ONLY_OPS)
    allowed.update({OP_SDIO_SET_EXT_DEVICE_PROP_VALUE, OP_SDIO_CONTROL_DEVICE})
    if args.sdk_handshake:
        allowed.add(OP_SDIO_SET_REMOTE_SDK_INFO)

    print("=== experiment_a6700: SESSION-ONLY writes (volatile) ===")
    dev = None
    try:
        dev = open_and_connect(args.pid, allowed, sdk_handshake=args.sdk_handshake)
        if args.test_aspect_3_2:
            test_aspect_3_2(dev)
        if args.test_burst_trigger:
            test_burst_trigger(dev, args.drive_value)
    except PtpError as e:
        sys.exit(f"[ERROR] {e}")
    except usb.core.USBError as e:
        sys.exit(f"[USB ERROR] {e}\n"
                 "On Windows: install the WinUSB driver via Zadig (see README.md).")
    finally:
        if dev is not None:
            try:
                dev.transaction(OP_CLOSE_SESSION)
                print("\n[+] CloseSession(0x1003) -> session closed "
                      "(all changes were session-only).")
            except PtpError:
                pass
            dev.close()


if __name__ == "__main__":
    main()
