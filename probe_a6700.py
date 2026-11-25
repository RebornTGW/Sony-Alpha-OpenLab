#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_a6700.py - *Read-only* USB diagnostic probe for the Sony A6700 (ILCE-6700).

Purpose
-------
Establish a PTP/USB dialogue with the camera and read non-destructive information:
    1. OpenSession            (standard PTP opcode 0x1002)
    2. GetDeviceInfo          (standard PTP opcode 0x1001)   [read]
    3. SDIO Connect           (Sony vendor opcode  0x9201)   [session handshake]
    4. GetExtDeviceInfo       (Sony vendor opcode  0x9202)   [read capabilities]
    5. GetExtDevicePropDesc   (Sony vendor opcode  0x9203)   [read descriptors]

SAFETY GUARANTEE
----------------
This script is STRICTLY read-only. It issues NO write, trigger, or control
operation:
    - no SetExtDevicePropValue (0x9205)
    - no ControlDevice         (0x9207)  -> never S1/S2/Movie Rec
    - no SendObject / delete / format / firmware update
Every issued operation is validated against a whitelist (`READ_ONLY_OPS`). Any
attempt to issue another opcode raises an exception before anything is sent to
the camera.

Project scope: this tool supports two research goals only - Open Gate 3:2 and
multi-exposure - and performs no permanent modification of the camera.

This repository contains no file extracted from the Sony firmware: the PTP codes
used here are public protocol constants (PTP / ISO 15740) and the independently
documented Sony vendor "SDIO" space.

Dependencies: pyusb (+ libusb-1.0 / WinUSB driver via Zadig on Windows).
See README.md.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover
    sys.exit("[ERROR] pyusb is missing. Install it with: pip install pyusb")

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

SONY_VID = 0x054C  # Sony Corporation (USB vendor ID)

# USB interface class "Still Image / PTP"
USB_CLASS_STILL_IMAGE = 0x06

# PTP/USB container types
PTP_CONTAINER_COMMAND = 0x0001
PTP_CONTAINER_DATA = 0x0002
PTP_CONTAINER_RESPONSE = 0x0003
PTP_CONTAINER_EVENT = 0x0004

# Allowed opcodes (READ-ONLY). Any operation outside this set is refused by
# transaction().
OP_OPEN_SESSION = 0x1002
OP_CLOSE_SESSION = 0x1003
OP_GET_DEVICE_INFO = 0x1001
OP_SDIO_CONNECT = 0x9201
OP_SDIO_GET_EXT_DEVICE_INFO = 0x9202
OP_SDIO_GET_EXT_DEVICE_PROP_DESC = 0x9203

READ_ONLY_OPS = {
    OP_OPEN_SESSION,
    OP_CLOSE_SESSION,
    OP_GET_DEVICE_INFO,
    OP_SDIO_CONNECT,
    OP_SDIO_GET_EXT_DEVICE_INFO,
    OP_SDIO_GET_EXT_DEVICE_PROP_DESC,
}

OP_NAMES = {
    OP_OPEN_SESSION: "OpenSession",
    OP_CLOSE_SESSION: "CloseSession",
    OP_GET_DEVICE_INFO: "GetDeviceInfo",
    OP_SDIO_CONNECT: "SDIO_Connect",
    OP_SDIO_GET_EXT_DEVICE_INFO: "SDIO_GetExtDeviceInfo",
    OP_SDIO_GET_EXT_DEVICE_PROP_DESC: "SDIO_GetExtDevicePropDesc",
}

PTP_RC_OK = 0x2001  # "OK" response code

# A few symbolic DevicePropCode names, for display only
# (protocol constants only; no firmware data).
PROP_NAMES = {
    0x5013: "still_capture_mode (drive mode)",
    0xD211: "aspect_ratio",
    0xD241: "file_format_movie",
    0xD242: "recording_setting_movie",
    0xD21E: "iso_sensitivity",
    0xD20D: "shutter_speed",
}

DEFAULT_TIMEOUT_MS = 4000


# ---------------------------------------------------------------------------
# PTP/USB container layer
# ---------------------------------------------------------------------------

class PtpError(RuntimeError):
    pass


class PtpUsbDevice:
    """Minimal PTP transport on top of pyusb (bulk-in / bulk-out)."""

    def __init__(self, dev: "usb.core.Device", intf, ep_in, ep_out):
        self.dev = dev
        self.intf = intf
        self.ep_in = ep_in
        self.ep_out = ep_out
        self._txid = 0

    # -- discovery --------------------------------------------------------

    @classmethod
    def open_first(cls, vid: int = SONY_VID, pid: int | None = None) -> "PtpUsbDevice":
        kwargs = {"idVendor": vid, "find_all": True}
        if pid is not None:
            kwargs["idProduct"] = pid

        # On Windows, pyusb often raises NoBackendError because it cannot locate a
        # libusb-1.0 DLL on its own. `libusb-package` ships a prebuilt backend, so
        # use it when available; otherwise fall back to pyusb's default discovery.
        try:
            import libusb_package
            backend = libusb_package.get_libusb1_backend()
        except ImportError:
            backend = None
        if backend is not None:
            kwargs["backend"] = backend

        candidates = list(usb.core.find(**kwargs))
        if not candidates:
            raise PtpError(
                f"No Sony USB device found (VID 0x{vid:04X}). "
                "Is the camera powered on, in 'PC Remote' mode and connected over USB?"
            )

        for dev in candidates:
            intf = cls._find_ptp_interface(dev)
            if intf is None:
                continue
            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: (
                    usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT
                    and usb.util.endpoint_type(e.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
                ),
            )
            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: (
                    usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_IN
                    and usb.util.endpoint_type(e.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
                ),
            )
            if ep_in is None or ep_out is None:
                continue

            # On Windows there is no kernel driver to detach (WinUSB).
            try:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
            except (NotImplementedError, usb.core.USBError):
                pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                # Already configured: carry on.
                pass
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
            return cls(dev, intf, ep_in, ep_out)

        raise PtpError(
            "A Sony device was found but no usable PTP interface (class 0x06). "
            "Check the camera's USB connection mode (PC Remote / PTP) and the "
            "WinUSB driver (Zadig)."
        )

    @staticmethod
    def _find_ptp_interface(dev):
        try:
            for cfg in dev:
                for intf in cfg:
                    if intf.bInterfaceClass == USB_CLASS_STILL_IMAGE:
                        return intf
        except usb.core.USBError:
            return None
        return None

    def close(self):
        try:
            usb.util.release_interface(self.dev, self.intf.bInterfaceNumber)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)

    # -- transaction ------------------------------------------------------

    def _next_txid(self) -> int:
        self._txid = (self._txid + 1) & 0xFFFFFFFF
        return self._txid

    def transaction(self, opcode: int, params=(), timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """Issue a PTP operation (command phase, data phase in RECEPTION only,
        response phase) and return (response_code, data_bytes).

        Refuses any opcode absent from the READ_ONLY_OPS whitelist.
        Never performs a data phase in transmission (no writes).
        """
        if opcode not in READ_ONLY_OPS:
            raise PtpError(
                f"REFUSED: opcode 0x{opcode:04X} is not in the read-only whitelist. "
                "This script issues no write/control operation."
            )

        params = list(params)
        if len(params) > 5:
            raise PtpError("PTP: at most 5 parameters per operation.")

        txid = self._next_txid()

        # --- Command phase ---
        body = struct.pack("<HHI", PTP_CONTAINER_COMMAND, opcode, txid)
        body += b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params)
        packet = struct.pack("<I", len(body) + 4) + body
        self.ep_out.write(packet, timeout_ms)

        # --- Data phase (reception, if any) ---
        data = b""
        first = self._read_container(timeout_ms)
        ctype = first["type"]
        if ctype == PTP_CONTAINER_DATA:
            data = first["payload"]
            resp = self._read_container(timeout_ms)
        elif ctype == PTP_CONTAINER_RESPONSE:
            resp = first
        else:
            raise PtpError(f"Unexpected container type=0x{ctype:04X}")

        if resp["type"] != PTP_CONTAINER_RESPONSE:
            raise PtpError(f"Missing PTP response (type=0x{resp['type']:04X})")

        return resp["code"], data

    def _read_container(self, timeout_ms: int):
        raw = bytes(self.ep_in.read(self.ep_in.wMaxPacketSize * 8, timeout_ms))
        if len(raw) < 12:
            raise PtpError("Truncated PTP container (incomplete header).")
        length, ctype, code, txid = struct.unpack_from("<IHHI", raw, 0)
        payload = raw[12:length]
        # Pull the rest of the data if the message spans several transfers.
        while len(raw) < length:
            chunk = bytes(self.ep_in.read(self.ep_in.wMaxPacketSize * 8, timeout_ms))
            if not chunk:
                break
            raw += chunk
            payload = raw[12:length]
        return {"length": length, "type": ctype, "code": code,
                "txid": txid, "payload": payload}


# ---------------------------------------------------------------------------
# Minimal PTP dataset decoding
# ---------------------------------------------------------------------------

def _read_ptp_string(buf: bytes, off: int):
    """PTP string: 1 byte (number of characters) + UTF-16LE."""
    if off >= len(buf):
        return "", off
    n = buf[off]
    off += 1
    if n == 0:
        return "", off
    raw = buf[off:off + (n * 2)]
    off += n * 2
    s = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return s, off


def _read_uint16_array(buf: bytes, off: int):
    (count,) = struct.unpack_from("<I", buf, off)
    off += 4
    vals = list(struct.unpack_from("<%dH" % count, buf, off))
    off += count * 2
    return vals, off


def parse_device_info(data: bytes) -> dict:
    """Decode the useful fields of the DeviceInfo dataset (GetDeviceInfo)."""
    info = {}
    try:
        off = 0
        std_ver, vendor_ext_id, vendor_ext_ver = struct.unpack_from("<HIH", data, off)
        off += 8
        info["standard_version"] = std_ver
        info["vendor_extension_id"] = vendor_ext_id
        info["vendor_extension_version"] = vendor_ext_ver
        info["vendor_extension_desc"], off = _read_ptp_string(data, off)
        # functional mode (uint16)
        off += 2
        info["operations_supported"], off = _read_uint16_array(data, off)
        info["events_supported"], off = _read_uint16_array(data, off)
        info["device_properties_supported"], off = _read_uint16_array(data, off)
        info["capture_formats"], off = _read_uint16_array(data, off)
        info["image_formats"], off = _read_uint16_array(data, off)
        info["manufacturer"], off = _read_ptp_string(data, off)
        info["model"], off = _read_ptp_string(data, off)
        info["device_version"], off = _read_ptp_string(data, off)
        info["serial_number"], off = _read_ptp_string(data, off)
    except (struct.error, IndexError):
        info["_parse_warning"] = "DeviceInfo dataset truncated / non-standard"
    return info


# ---------------------------------------------------------------------------
# Diagnostic sequence
# ---------------------------------------------------------------------------

def rc_str(rc: int) -> str:
    return "OK" if rc == PTP_RC_OK else f"0x{rc:04X}"


def run_probe(pid: int | None, do_sdio: bool = True):
    print("=== probe_a6700: READ-ONLY USB diagnostic ===\n")
    dev = PtpUsbDevice.open_first(pid=pid)
    print(f"[+] PTP device opened "
          f"(VID 0x{dev.dev.idVendor:04X} PID 0x{dev.dev.idProduct:04X}, "
          f"interface #{dev.intf.bInterfaceNumber}).\n")

    try:
        # 1) OpenSession
        rc, _ = dev.transaction(OP_OPEN_SESSION, params=[1])
        print(f"[1] OpenSession(0x1002)          -> {rc_str(rc)}")
        if rc != PTP_RC_OK:
            print("    (session not opened, aborting.)")
            return

        # 2) GetDeviceInfo (read)
        rc, data = dev.transaction(OP_GET_DEVICE_INFO)
        print(f"[2] GetDeviceInfo(0x1001)        -> {rc_str(rc)} ({len(data)} bytes)")
        if rc == PTP_RC_OK and data:
            di = parse_device_info(data)
            print(f"      Manufacturer     : {di.get('manufacturer','?')}")
            print(f"      Model            : {di.get('model','?')}")
            print(f"      Firmware version : {di.get('device_version','?')}")
            print(f"      Serial number    : {di.get('serial_number','?')}")
            print(f"      Vendor extension : id=0x{di.get('vendor_extension_id',0):X}"
                  f" \"{di.get('vendor_extension_desc','')}\"")
            ops = di.get("operations_supported", [])
            props = di.get("device_properties_supported", [])
            print(f"      Operations       : {len(ops)} "
                  f"(vendor 0x92xx: {sum(1 for o in ops if 0x9200 <= o <= 0x92FF)})")
            print(f"      Properties       : {len(props)}")

        if not do_sdio:
            return

        # 3) SDIO Connect - extended-session handshake (read/negotiation)
        #    2-phase negotiation; no camera setting is modified.
        for phase in (1, 2):
            rc, _ = dev.transaction(OP_SDIO_CONNECT, params=[phase, 0x0000DA01, 0])
            print(f"[3] SDIO_Connect(0x9201) ph{phase}     -> {rc_str(rc)}")
            time.sleep(0.05)

        # 4) GetExtDeviceInfo (read extended capabilities)
        rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x00C8])
        print(f"[4] SDIO_GetExtDeviceInfo(0x9202)-> {rc_str(rc)} ({len(data)} bytes)")

        # 5) GetExtDevicePropDesc (read a few safe descriptors)
        for code in (0x5013, 0xD211, 0xD241):
            rc, data = dev.transaction(
                OP_SDIO_GET_EXT_DEVICE_PROP_DESC, params=[code]
            )
            name = PROP_NAMES.get(code, f"0x{code:04X}")
            print(f"[5] GetExtDevicePropDesc {name:<28} "
                  f"-> {rc_str(rc)} ({len(data)} bytes)")

    finally:
        # Clean session close (read-only).
        try:
            dev.transaction(OP_CLOSE_SESSION)
            print("\n[+] CloseSession(0x1003)         -> session closed.")
        except PtpError:
            pass
        dev.close()


def main():
    ap = argparse.ArgumentParser(
        description="Read-only USB diagnostic probe for the Sony A6700."
    )
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None,
                    help="Explicit USB PID (e.g. 0x0DE7). Default: auto.")
    ap.add_argument("--no-sdio", action="store_true",
                    help="Stop after GetDeviceInfo (standard PTP only).")
    args = ap.parse_args()

    try:
        run_probe(pid=args.pid, do_sdio=not args.no_sdio)
    except PtpError as e:
        sys.exit(f"[ERROR] {e}")
    except usb.core.USBError as e:
        sys.exit(f"[USB ERROR] {e}\n"
                 "On Windows: install the WinUSB driver on the camera's PTP "
                 "interface via Zadig (see README.md).")


if __name__ == "__main__":
    main()
