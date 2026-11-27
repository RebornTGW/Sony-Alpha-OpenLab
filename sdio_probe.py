#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sdio_probe.py - *Read-only* BIONZ XR PTP/SDIO v300 diagnostic probe.

Companion to `probe_a6700.py` (which already performs the live v300 handshake
and prints a human-readable report). This module adds the pieces that script
does not have:

    - a *structured* decoder for GetAllExtDevicePropInfo (0x9209) that returns
      plain dicts/lists instead of printing, so results can be exported;
    - `--dump-bin` to save the raw 0x9209 payload from a live camera;
    - `--parse-bin` to decode a previously-saved dump completely offline, with
      no USB/camera needed - useful for regression tests and for sharing a
      capture with someone who doesn't have the hardware;
    - `--json` to export the decoded property map.

The default decoder targets SDIO v300 (SDK version 0x012C): an 8-byte
stream header (count + reserved, both u32) followed by records with no
padding byte and, on a form=0x02 (enum) property, two back-to-back lists
("Supported" then "Available"). Verified live by cross-referencing the
ordered property-code list from SDIO_GetExtDeviceInfo (0x9202) against
GetAllExtDevicePropInfo (0x9209): every record boundary found that way
decoded with zero leftover bytes. `--single-enum` switches to the older
SDIO v200 shape (SDK 0x00C8) instead. See docs/BIONZ_XR_PTP_SDIO.md.

Reuses `probe_a6700.py`'s PTP/USB transport (`PtpUsbDevice`) and dataset
helpers (`parse_device_info`, PTP string/array readers) rather than
duplicating them. The USB vendor ID, container framing, and the Sony SDIO
handshake order below are the same ones verified live on the ILCE-6700
(firmware 2.00) PC Remote PID (`054C:0E78`); see `docs/BIONZ_XR_PTP_SDIO.md`.

SAFETY GUARANTEE
-----------------
Strictly read-only, like `probe_a6700.py`. The only opcodes this module ever
sends are OpenSession, CloseSession, GetDeviceInfo, SDIO_Connect,
SDIO_GetExtDeviceInfo, and SDIO_GetAllExtDevicePropInfo - all in
`probe_a6700.READ_ONLY_OPS`. No SetExtDevicePropValue (0x9205), no
ControlDevice (0x9207), no write of any kind.

This repository contains no file extracted from the Sony firmware: the PTP
codes used here are public protocol constants (PTP / ISO 15740) and the
independently documented Sony vendor "SDIO" space.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time

from probe_a6700 import (
    OP_CLOSE_SESSION,
    OP_GET_DEVICE_INFO,
    OP_OPEN_SESSION,
    OP_SDIO_CONNECT,
    OP_SDIO_GET_ALL_EXT_DEVICE_PROP_INFO,
    OP_SDIO_GET_EXT_DEVICE_INFO,
    PTP_RC_OK,
    PtpError,
    PtpUsbDevice,
    READ_ONLY_OPS,
    _read_ptp_string,
    parse_device_info,
    prop_name,
)

# ---------------------------------------------------------------------------
# PTP data type codes, including the array flag.
# ---------------------------------------------------------------------------

# Standard PTP: a datatype code with bit 0x4000 set means "array of the base
# type" (ISO 15740 Annex D). The base type is the low bits with that flag
# cleared. This is a protocol-level constant, not anything device-specific.
PTP_ARRAY_FLAG = 0x4000

PTP_BASE_TYPES = {
    0x0001: ("INT8", 1), 0x0002: ("UINT8", 1),
    0x0003: ("INT16", 2), 0x0004: ("UINT16", 2),
    0x0005: ("INT32", 4), 0x0006: ("UINT32", 4),
    0x0007: ("INT64", 8), 0x0008: ("UINT64", 8),
    0x0009: ("INT128", 16), 0x000A: ("UINT128", 16),
    0xFFFF: ("STR", 0),
}

FORM_NONE = 0x00
FORM_RANGE = 0x01
FORM_ENUM = 0x02


def _split_dtype(dtype: int):
    """(base_type, is_array). 0xFFFF (STR) is its own scalar code and must
    never be treated as array-flagged even though 0xFFFF & 0x4000 != 0 -
    every bit in 0xFFFF is set, including the array flag bit, so it has to
    be special-cased before masking."""
    if dtype == 0xFFFF:
        return 0xFFFF, False
    return dtype & ~PTP_ARRAY_FLAG, bool(dtype & PTP_ARRAY_FLAG)


def _type_name(dtype: int) -> str:
    base, is_array = _split_dtype(dtype)
    name, _size = PTP_BASE_TYPES.get(base, ("0x%04X" % base, 0))
    return f"ARRAY<{name}>" if is_array else name


class SdioDecodeError(RuntimeError):
    pass


def _read_scalar(buf: bytes, off: int, base_type: int):
    """Read one scalar PTP value of `base_type` (array flag already stripped)."""
    name, size = PTP_BASE_TYPES.get(base_type, ("?", 0))
    if base_type == 0xFFFF:
        return _read_ptp_string(buf, off)
    if size == 0:
        raise SdioDecodeError(f"unsupported scalar dtype 0x{base_type:04X}")
    if off + size > len(buf):
        raise SdioDecodeError("truncated scalar value")
    signed = name.startswith("INT") and not name.startswith("UINT")
    val = int.from_bytes(buf[off:off + size], "little", signed=signed)
    return val, off + size


def _read_dpv(buf: bytes, off: int, dtype: int):
    """Read one property value (scalar, or - if bit 0x4000 is set - an array
    of the base type, PTP-standard count-prefixed with a uint32 element
    count)."""
    base, is_array = _split_dtype(dtype)
    if not is_array:
        return _read_scalar(buf, off, base)
    if off + 4 > len(buf):
        raise SdioDecodeError("truncated array count")
    (count,) = struct.unpack_from("<I", buf, off)
    off += 4
    vals = []
    for _ in range(count):
        v, off = _read_scalar(buf, off, base)
        vals.append(v)
    return vals, off


def parse_ext_device_prop_record(data: bytes, off: int = 0, single_enum: bool = False):
    """Decode one Sony SDIO v300 DevicePropDesc record starting at `off`.

    Verified live on the A6700 (firmware 2.00, SDK version 0x012C) by
    cross-referencing the ordered property-code list from
    SDIO_GetExtDeviceInfo (0x9202) against GetAllExtDevicePropInfo (0x9209):
    every record boundary found that way decoded with **zero leftover
    bytes**, for three records of three different shapes (none/range/enum).
    See docs/BIONZ_XR_PTP_SDIO.md.

    Layout (v300, default): code(2) type(2) GetSet(1) Enable(1)
    FactoryDefault(DTS) CurrentValue(DTS) FormFlag(1) [form]. No padding
    byte between Enable and FactoryDefault - that extra byte is a quirk of
    the *older* SDIO v200 dataset (SDK version 0x00C8), not this one.

    form == 0x01 (Range): min, max, step (DTS each).
    form == 0x02 (Enum, v300): u16 count + count x DTS ("Supported" values),
      followed immediately by a *second* u16 count + count x DTS
      ("Available" values, the camera-state-dependent subset of Supported).
      Confirmed live: e.g. 0xD211 aspect_ratio decodes as
      Supported=[1,3,2,4], Available=[1,3,2,4], current=2, with the record
      ending exactly at the next known property code - nothing unaccounted
      for.

    `single_enum=True` switches to the **legacy SDIO v200** shape instead
    (SDK version 0x00C8): the extra padding byte after Enable, and only a
    *single* enum list (no Available list). Use this for an older dump; it
    is not the default because 0x012C - what every live capture in this
    project actually negotiates - uses the v300 shape above.

    Returns (record_dict, next_offset) or raises SdioDecodeError.
    """
    header_len = 7 if single_enum else 6
    if off + header_len > len(data):
        raise SdioDecodeError("truncated record header")
    code = struct.unpack_from("<H", data, off)[0]
    dtype = struct.unpack_from("<H", data, off + 2)[0]
    base, _is_array = _split_dtype(dtype)
    if base not in PTP_BASE_TYPES:
        raise SdioDecodeError(f"unknown base dtype 0x{base:04X} at offset {off}")
    getset = data[off + 4]
    enabled = data[off + 5]
    p = off + header_len  # v300: no padding; v200 (single_enum): skip extra byte at off+6

    default, p = _read_dpv(data, p, dtype)
    current, p = _read_dpv(data, p, dtype)
    if p >= len(data):
        raise SdioDecodeError("truncated record (missing form flag)")
    form = data[p]
    p += 1

    record = {
        "code": code,
        "name": prop_name(code),
        "dtype": dtype,
        "dtype_name": _type_name(dtype),
        "getset": "Get/Set" if getset == 1 else "Get only",
        "enabled": bool(enabled),
        "default": default,
        "current": current,
        "form": form,
        "enum": None,
        "available": None,
        "range": None,
    }

    if form == FORM_RANGE:
        vmin, p = _read_dpv(data, p, dtype)
        vmax, p = _read_dpv(data, p, dtype)
        vstep, p = _read_dpv(data, p, dtype)
        record["range"] = {"min": vmin, "max": vmax, "step": vstep}
    elif form == FORM_ENUM:
        if p + 2 > len(data):
            raise SdioDecodeError("truncated enum count")
        n = struct.unpack_from("<H", data, p)[0]
        p += 2
        values = []
        for _ in range(n):
            v, p = _read_dpv(data, p, dtype)
            values.append(v)
        record["enum"] = values
        if not single_enum:
            # v300: a second "Available" list always follows the first.
            if p + 2 > len(data):
                raise SdioDecodeError("truncated available-list count")
            n2 = struct.unpack_from("<H", data, p)[0]
            p += 2
            avail = []
            for _ in range(n2):
                v, p = _read_dpv(data, p, dtype)
                avail.append(v)
            record["available"] = avail
    elif form != FORM_NONE:
        raise SdioDecodeError(f"unknown form flag 0x{form:02X} at offset {off}")

    return record, p


def parse_all_ext_prop_info(data: bytes, single_enum: bool = False) -> list:
    """Decode the full GetAllExtDevicePropInfo (0x9209) stream into a list of
    record dicts (see `parse_ext_device_prop_record`).

    v300 (default): the stream starts with an 8-byte header - count(u32) +
    reserved(u32, always 0 on every live capture so far) - before the first
    record. `single_enum=True` (legacy v200) has no such header; records
    start at offset 0.

    Stops cleanly - and keeps every record decoded so far - the moment a
    record fails to parse, rather than raising, since a stream captured
    from a different firmware or camera mode may end differently than ours.
    """
    if single_enum:
        off = 0
    else:
        if len(data) < 8:
            return []
        off = 8
    records = []
    while off < len(data):
        try:
            record, off = parse_ext_device_prop_record(data, off, single_enum)
        except SdioDecodeError:
            break
        records.append(record)
    return records


def records_to_json(records: list) -> dict:
    """{"0xD211": {...}, ...} - hex-keyed so it reads next to the PTP docs."""
    return {f"0x{r['code']:04X}": r for r in records}


# ---------------------------------------------------------------------------
# Live capture (read-only)
# ---------------------------------------------------------------------------

def rc_str(rc: int) -> str:
    return "OK" if rc == PTP_RC_OK else f"0x{rc:04X}"


def capture_all_ext_prop_info(pid: int | None = None, verbose: bool = False) -> bytes:
    """Run the verified-live Sony SDIO v300 handshake and return the raw
    GetAllExtDevicePropInfo (0x9209) payload. Strictly read-only; every
    opcode sent is in `probe_a6700.READ_ONLY_OPS`.

    Sequence (confirmed on ILCE-6700 fw 2.00, PC Remote PID 0x0E78):
        OpenSession(1) -> SDIO_Connect(1,0,0) -> SDIO_Connect(2,0,0)
        -> SDIO_GetExtDeviceInfo(0x012C) -> SDIO_Connect(3,0,0)
        -> SDIO_GetAllExtDevicePropInfo(0,0)
    """
    dev = PtpUsbDevice.open_first(pid=pid, allowed_ops=READ_ONLY_OPS)
    if verbose:
        print(f"[+] PTP device opened (VID 0x{dev.dev.idVendor:04X} "
              f"PID 0x{dev.dev.idProduct:04X}).")
    try:
        rc, _ = dev.transaction(OP_OPEN_SESSION, params=[1])
        if verbose:
            print(f"[1] OpenSession(0x1002)              -> {rc_str(rc)}")
        if rc != PTP_RC_OK:
            raise PtpError(f"OpenSession failed: {rc_str(rc)}")

        rc, data = dev.transaction(OP_GET_DEVICE_INFO)
        if verbose and rc == PTP_RC_OK and data:
            di = parse_device_info(data)
            ops = di.get("operations_supported", [])
            vendor_ops = [o for o in ops if 0x9200 <= o <= 0x92FF]
            print(f"[2] GetDeviceInfo(0x1001)            -> {rc_str(rc)} "
                  f"model={di.get('model', '?')} fw={di.get('device_version', '?')} "
                  f"vendor-ops={len(vendor_ops)}")

        for phase in (1, 2):
            rc, data = dev.transaction(OP_SDIO_CONNECT, params=[phase, 0, 0])
            if verbose:
                print(f"[3] SDIO_Connect(0x9201) ph{phase}         -> {rc_str(rc)} "
                      f"({len(data)} bytes data)")
            if rc != PTP_RC_OK:
                raise PtpError(f"SDIO_Connect phase {phase} failed: {rc_str(rc)}")
            time.sleep(0.05)

        rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x012C])
        if rc != PTP_RC_OK:
            rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x00C8])
        if verbose:
            print(f"[4] SDIO_GetExtDeviceInfo(0x9202)    -> {rc_str(rc)} "
                  f"({len(data)} bytes)")
        if rc != PTP_RC_OK:
            raise PtpError(f"SDIO_GetExtDeviceInfo failed: {rc_str(rc)}")

        rc, data = dev.transaction(OP_SDIO_CONNECT, params=[3, 0, 0])
        if verbose:
            print(f"[3] SDIO_Connect(0x9201) ph3         -> {rc_str(rc)} "
                  f"({len(data)} bytes data)")
        if rc != PTP_RC_OK:
            raise PtpError(f"SDIO_Connect phase 3 failed: {rc_str(rc)}")

        rc, data = dev.transaction(OP_SDIO_GET_ALL_EXT_DEVICE_PROP_INFO, params=[0])
        if verbose:
            print(f"[5] SDIO_GetAllExtDevicePropInfo(0x9209) -> {rc_str(rc)} "
                  f"({len(data)} bytes)")
        if rc != PTP_RC_OK:
            raise PtpError(f"SDIO_GetAllExtDevicePropInfo failed: {rc_str(rc)}")
        return data
    finally:
        try:
            dev.transaction(OP_CLOSE_SESSION)
        except PtpError:
            pass
        dev.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(records: list, verbose: bool = False) -> None:
    print(f"Decoded {len(records)} property record(s).")
    video_codes = (0x5013, 0xD211, 0xD219, 0xD21D, 0xD241, 0xD242, 0xD286)
    shown = records if verbose else [r for r in records if r["code"] in video_codes]
    label = "all" if verbose else "video/aspect-related"
    print(f"\n{label} records:")
    for r in shown:
        print(f"  0x{r['code']:04X} {r['name']:<30} type={r['dtype_name']:<12} "
              f"{r['getset']:<9} enabled={r['enabled']}")
        print(f"      current={r['current']!r}  default={r['default']!r}")
        if r["range"] is not None:
            print(f"      range: min={r['range']['min']} max={r['range']['max']} "
                  f"step={r['range']['step']}")
        elif r["enum"] is not None:
            vals = ", ".join(str(v) for v in r["enum"][:16])
            more = " ..." if len(r["enum"]) > 16 else ""
            print(f"      supported ({len(r['enum'])}): {vals}{more}")
            if r["available"] is not None:
                avals = ", ".join(str(v) for v in r["available"][:16])
                amore = " ..." if len(r["available"]) > 16 else ""
                print(f"      available ({len(r['available'])}): {avals}{amore}")
    if not verbose:
        print("\n(use --verbose for the full record list)")


def main():
    ap = argparse.ArgumentParser(
        description="Read-only BIONZ XR PTP/SDIO v300 diagnostic probe "
                     "(GetAllExtDevicePropInfo 0x9209 decoder)."
    )
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None,
                     help="Explicit USB PID (e.g. 0x0E78). Default: auto.")
    ap.add_argument("--dump-bin", metavar="PATH",
                     help="Capture the raw 0x9209 payload from a live camera "
                          "and save it to PATH (also decodes and prints it).")
    ap.add_argument("--parse-bin", metavar="PATH",
                     help="Decode a previously saved 0x9209 dump offline. "
                          "No camera/USB needed.")
    ap.add_argument("--json", metavar="PATH",
                     help="Export the decoded property map as JSON to PATH.")
    ap.add_argument("--single-enum", action="store_true",
                     help="Decode as legacy SDIO v200 (SDK 0x00C8): no stream "
                          "header, extra padding byte per record, single "
                          "enum list. Default is v300 (SDK 0x012C, dual "
                          "Supported+Available list) - what every live "
                          "capture in this project actually negotiates.")
    ap.add_argument("--verbose", "-v", action="store_true",
                     help="Print every decoded record, not just the video ones.")
    args = ap.parse_args()

    if args.dump_bin and args.parse_bin:
        sys.exit("[ERROR] --dump-bin and --parse-bin are mutually exclusive.")

    if args.parse_bin:
        with open(args.parse_bin, "rb") as fh:
            raw = fh.read()
        print(f"[+] Loaded {len(raw)} bytes from {args.parse_bin} (offline, no camera).")
    else:
        try:
            raw = capture_all_ext_prop_info(pid=args.pid, verbose=True)
        except PtpError as e:
            sys.exit(f"[ERROR] {e}")
        except Exception as e:  # pragma: no cover - depends on real USB stack
            sys.exit(f"[USB ERROR] {e}\n"
                      "On Windows: install the WinUSB driver on the camera's "
                      "PTP interface via Zadig (see README.md).")
        if args.dump_bin:
            with open(args.dump_bin, "wb") as fh:
                fh.write(raw)
            print(f"[+] Saved {len(raw)} bytes to {args.dump_bin}")

    records = parse_all_ext_prop_info(raw, single_enum=args.single_enum)
    _print_report(records, verbose=args.verbose)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(records_to_json(records), fh, indent=2)
        print(f"\n[+] Wrote decoded property map to {args.json}")


if __name__ == "__main__":
    main()
