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

# Symbolic name dictionaries (protocol constants only; no firmware data).
# Loaded from the generated reference module sony_codes.py when available.
try:
    from sony_codes import DEVICE_PROP_NAMES, VENDOR_OP_NAMES
except ImportError:  # minimal fallback if the module is missing
    DEVICE_PROP_NAMES = {
        0x5013: "still_capture_mode", 0xD211: "aspect_ratio",
        0xD241: "file_format_movie", 0xD242: "recording_setting_movie",
        0xD2C1: "s1_button", 0xD2C2: "s2_button", 0xD2C8: "movie_rec_button",
    }
    VENDOR_OP_NAMES = {
        0x9201: "SDIO_Connect", 0x9202: "SDIO_GetExtDeviceInfo",
        0x9203: "GetExtDevicePropDesc", 0x9205: "SetExtDevicePropValue",
        0x9207: "ControlDevice",
    }

# PTP data types (code -> (name, byte_size)); size 0 = variable (string/array).
PTP_DATATYPES = {
    0x0001: ("INT8", 1), 0x0002: ("UINT8", 1),
    0x0003: ("INT16", 2), 0x0004: ("UINT16", 2),
    0x0005: ("INT32", 4), 0x0006: ("UINT32", 4),
    0x0007: ("INT64", 8), 0x0008: ("UINT64", 8),
    0xFFFF: ("STR", 0),
}

DEFAULT_TIMEOUT_MS = 4000


def prop_name(code: int) -> str:
    """Human label for a DevicePropCode / ControlDevice code."""
    return DEVICE_PROP_NAMES.get(code, "(unknown)")


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

            # Preventive cleanup: clear any residual halt/stall condition on the
            # bulk endpoints so a previous aborted transfer cannot cause timeouts.
            for ep in (ep_in, ep_out):
                try:
                    dev.clear_halt(ep.bEndpointAddress)
                except (usb.core.USBError, NotImplementedError):
                    pass

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


def _is_prop_code(v: int) -> bool:
    """True if v looks like a Sony DevicePropCode / ControlDevice code."""
    return (0x5000 <= v <= 0x50FF) or (0xD100 <= v <= 0xD3FF)


def decode_ext_device_info(data: bytes):
    """Decode SDIO_GetExtDeviceInfo (0x9202): list the DeviceProp / ControlDevice
    codes the camera exposes live.

    The dataset starts with a uint16 version followed by uint16-counted arrays of
    uint16 codes. We parse those arrays defensively and, as a robust cross-check,
    also scan the whole payload for known code values. Read-only decoding.
    """
    if len(data) < 4:
        print("      (no extended device-info payload)")
        return

    version = struct.unpack_from("<H", data, 0)[0]
    print(f"      Dataset version  : 0x{version:04X} ({version})")

    # Greedy array parse: [u16 count][count x u16] blocks after the version.
    off = 2
    arrays = []
    while off + 2 <= len(data):
        count = struct.unpack_from("<H", data, off)[0]
        if count == 0 or off + 2 + count * 2 > len(data) or count > 4096:
            break
        vals = list(struct.unpack_from("<%dH" % count, data, off + 2))
        # Only trust the block if most entries look like real codes.
        if sum(1 for v in vals if _is_prop_code(v)) < max(1, len(vals) // 2):
            break
        arrays.append(vals)
        off += 2 + count * 2

    # Robust cross-check: all known codes anywhere in the payload (16-bit aligned).
    scanned = []
    seen = set()
    for i in range(0, len(data) - 1, 2):
        v = struct.unpack_from("<H", data, i)[0]
        if _is_prop_code(v) and v not in seen:
            seen.add(v)
            scanned.append(v)

    codes = []
    for a in arrays:
        codes.extend(a)
    if not codes:
        codes = scanned  # fall back to the scan if structured parse found nothing

    props = sorted({c for c in codes if not (0xD2C0 <= c <= 0xD3FF)})
    ctrls = sorted({c for c in codes if 0xD2C0 <= c <= 0xD3FF})

    if arrays:
        print(f"      Parsed arrays    : {len(arrays)} "
              f"({', '.join(str(len(a)) for a in arrays)} entries)")
    print(f"      Exposed properties ({len(props)}):")
    for c in props:
        print(f"        0x{c:04X}  {prop_name(c)}")
    print(f"      Exposed control/trigger codes ({len(ctrls)}):")
    for c in ctrls:
        print(f"        0x{c:04X}  {prop_name(c)}")


def _read_dpv(data: bytes, off: int, dtype: int):
    """Read one PTP property value of the given data type. Returns (value, off)."""
    name, size = PTP_DATATYPES.get(dtype, ("?", 0))
    if size == 0:  # string / unknown -> stop cleanly
        s, off = _read_ptp_string(data, off)
        return s, off
    signed = name.startswith("INT") and not name.startswith("UINT")
    val = int.from_bytes(data[off:off + size], "little", signed=signed)
    return val, off + size


def decode_prop_desc(code: int, data: bytes):
    """Decode a Sony DevicePropDesc returned by GetExtDevicePropDesc (0x9203):
    data type, GetSet access, current value and the allowed values (enum/range).

    Sony layout: code(2) type(2) GetSet(1) Enable(1) FactoryDefault(DTS)
    CurrentValue(DTS) FormFlag(1) [form]. Defensive: on any mismatch, falls back
    to a raw hex dump so nothing is lost.
    """
    label = prop_name(code)
    if not data:
        print(f"        -> 0x{code:04X} {label}: empty descriptor "
              "(property not available in the current camera mode)")
        return
    try:
        pcode = struct.unpack_from("<H", data, 0)[0]
        dtype = struct.unpack_from("<H", data, 2)[0]
        getset = data[4]
        enable = data[5]
        off = 6
        default, off = _read_dpv(data, off, dtype)
        current, off = _read_dpv(data, off, dtype)
        form = data[off]; off += 1

        tname = PTP_DATATYPES.get(dtype, ("0x%04X" % dtype, 0))[0]
        gs = "Get/Set" if getset == 1 else "Get only"
        print(f"        -> 0x{pcode:04X} {label}")
        print(f"           type={tname}  access={gs}  enabled={enable}")
        print(f"           CurrentValue = {current}   (factory default = {default})")

        if form == 0x02:  # enumeration
            n = struct.unpack_from("<H", data, off)[0]; off += 2
            vals = []
            for _ in range(n):
                v, off = _read_dpv(data, off, dtype)
                vals.append(v)
            shown = ", ".join(str(v) for v in vals[:24])
            more = " …" if len(vals) > 24 else ""
            print(f"           FormEnum ({n} allowed): {shown}{more}")
        elif form == 0x01:  # range
            vmin, off = _read_dpv(data, off, dtype)
            vmax, off = _read_dpv(data, off, dtype)
            vstep, off = _read_dpv(data, off, dtype)
            print(f"           FormRange: min={vmin} max={vmax} step={vstep}")
        else:
            print("           Form: none")
    except (struct.error, IndexError):
        hex_dump = data.hex()
        print(f"        -> 0x{code:04X} {label}: could not decode "
              f"({len(data)} bytes), raw = {hex_dump}")


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
            vendor_ops = [o for o in ops if 0x9200 <= o <= 0x92FF]
            print(f"      Operations       : {len(ops)} "
                  f"(vendor 0x92xx: {len(vendor_ops)})")
            print(f"      Properties       : {len(props)}")

            # 2b) Full list of vendor 0x92xx opcodes, cross-referenced with
            #     the documented names (docs/PROTOCOL.en.md).
            if vendor_ops:
                print(f"\n[2b] Vendor operations 0x92xx ({len(vendor_ops)}):")
                for o in sorted(vendor_ops):
                    print(f"       0x{o:04X}  {VENDOR_OP_NAMES.get(o, '(unknown)')}")
                print()

        if not do_sdio:
            return

        # 3) SDIO Connect handshake - standard Sony sequence (read-only).
        #    ph1 -> ph2 -> GetExtDeviceInfo -> ph3. Each Connect may return a
        #    PTP DATA phase; transaction() consumes it before the RESPONSE.
        for phase in (1, 2):
            rc, data = dev.transaction(OP_SDIO_CONNECT, params=[phase, 0, 0])
            extra = f" ({len(data)} bytes data)" if data else ""
            print(f"[3] SDIO_Connect(0x9201) ph{phase}     -> {rc_str(rc)}{extra}")
            time.sleep(0.05)

        # 4) GetExtDeviceInfo - SDK version 0x012C (300); fallback 0x00C8 (200).
        rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x012C])
        if rc != PTP_RC_OK:
            rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x00C8])
        print(f"[4] SDIO_GetExtDeviceInfo(0x9202)-> {rc_str(rc)} ({len(data)} bytes)")
        if rc == PTP_RC_OK and data:
            decode_ext_device_info(data)

        # 3c) SDIO Connect phase 3 - finalize the handshake.
        rc, data = dev.transaction(OP_SDIO_CONNECT, params=[3, 0, 0])
        extra = f" ({len(data)} bytes data)" if data else ""
        print(f"[3] SDIO_Connect(0x9201) ph3     -> {rc_str(rc)}{extra}")

        # 5) GetExtDevicePropDesc - read and decode a few safe descriptors
        #    (current value + allowed values). Read-only.
        print("\n[5] GetExtDevicePropDesc (decoded):")
        for code in (0x5013, 0xD211, 0xD241, 0xD242):
            rc, data = dev.transaction(
                OP_SDIO_GET_EXT_DEVICE_PROP_DESC, params=[code]
            )
            print(f"    0x{code:04X} {prop_name(code):<26} "
                  f"-> {rc_str(rc)} ({len(data)} bytes)")
            if rc == PTP_RC_OK:
                decode_prop_desc(code, data)

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
