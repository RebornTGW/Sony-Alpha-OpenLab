#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for sdio_probe.py: GetDeviceInfo parsing (reused from
probe_a6700) and the SDIO GetAllExtDevicePropInfo (0x9209) binary decoder -
built and checked entirely against synthetic byte fixtures, no live
USB/camera required.

The default (v300, SDK 0x012C) fixtures mirror the layout verified live on
the A6700 (firmware 2.00) by cross-referencing the ordered property-code
list from SDIO_GetExtDeviceInfo (0x9202) against GetAllExtDevicePropInfo
(0x9209): an 8-byte stream header, no per-record padding byte, and a dual
Supported+Available list on every enum property. `legacy=True` fixtures
cover the older SDIO v200 (SDK 0x00C8) shape instead.

Run from the repo root:  python -m unittest -v tests.test_sdio_probe
"""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sdio_probe as sp
from probe_a6700 import parse_device_info


def _ptp_string(s: str) -> bytes:
    """PTP string: 1 byte char count (incl. trailing NUL) + UTF-16LE."""
    if not s:
        return b"\x00"
    text = s + "\x00"
    return bytes([len(text)]) + text.encode("utf-16-le")


def _u16_array(vals) -> bytes:
    return struct.pack("<I", len(vals)) + b"".join(struct.pack("<H", v) for v in vals)


def stream_header(count: int) -> bytes:
    """v300 GetAllExtDevicePropInfo stream header: count(u32) + reserved(u32)."""
    return struct.pack("<II", count, 0)


def _record_header(code: int, dtype: int, getset: int, enabled: int,
                    legacy: bool = False) -> bytes:
    # v300 (default): code(2) type(2) getset(1) enable(1) - no padding.
    # legacy (v200): same + one extra padding byte, skipped by the decoder.
    h = struct.pack("<HHBB", code, dtype, getset, enabled)
    return h + b"\x00" if legacy else h


def _scalar(dtype: int, value) -> bytes:
    if dtype == 0xFFFF:
        return _ptp_string(value)
    size = sp.PTP_BASE_TYPES[dtype][1]
    return int(value).to_bytes(size, "little", signed=value < 0)


def build_none_record(code=0xD211, dtype=0x0004, value=2, legacy=False) -> bytes:
    """form=0x00 (None): just default + current, no range/enum tail."""
    return (
        _record_header(code, dtype, getset=1, enabled=1, legacy=legacy)
        + _scalar(dtype, value)  # default
        + _scalar(dtype, value)  # current
        + bytes([0x00])  # form = none
    )


def build_range_record(code=0x500E, dtype=0x0006, vmin=0, vmax=100, step=1,
                        default=0, current=50, legacy=False) -> bytes:
    return (
        _record_header(code, dtype, getset=1, enabled=1, legacy=legacy)
        + _scalar(dtype, default)
        + _scalar(dtype, current)
        + bytes([0x01])
        + _scalar(dtype, vmin)
        + _scalar(dtype, vmax)
        + _scalar(dtype, step)
    )


def build_enum_record(code=0x5013, dtype=0x0004, values=(1, 2, 3, 4),
                       default=1, current=2, available=None,
                       legacy=False) -> bytes:
    """v300 (default): always emits a second 'Available' list right after
    'Supported' - `available` defaults to the same values as `values` when
    not given. legacy=True emits only the single v200 list, ignoring
    `available` entirely (the older shape has no second list)."""
    body = (
        _record_header(code, dtype, getset=1, enabled=1, legacy=legacy)
        + _scalar(dtype, default)
        + _scalar(dtype, current)
        + bytes([0x02])
        + struct.pack("<H", len(values))
        + b"".join(_scalar(dtype, v) for v in values)
    )
    if legacy:
        return body
    avail = values if available is None else available
    return body + struct.pack("<H", len(avail)) + b"".join(
        _scalar(dtype, v) for v in avail
    )


def build_array_record(code=0xD219, values=(10, 20, 30), default=(), current=None,
                        legacy=False) -> bytes:
    dtype = 0x0004 | sp.PTP_ARRAY_FLAG  # ARRAY<UINT16>
    cur = current if current is not None else values
    return (
        _record_header(code, dtype, getset=0, enabled=1, legacy=legacy)
        + _u16_array(default)
        + _u16_array(cur)
        + bytes([0x00])
    )


def build_string_record(code=0xD21D, value="S-Log3", default="", current=None,
                         legacy=False) -> bytes:
    dtype = 0xFFFF
    cur = current if current is not None else value
    return (
        _record_header(code, dtype, getset=1, enabled=1, legacy=legacy)
        + _scalar(dtype, default)
        + _scalar(dtype, cur)
        + bytes([0x00])
    )


class TestTypeName(unittest.TestCase):
    def test_scalar_name(self):
        self.assertEqual(sp._type_name(0x0004), "UINT16")

    def test_array_name(self):
        self.assertEqual(sp._type_name(0x0004 | sp.PTP_ARRAY_FLAG), "ARRAY<UINT16>")

    def test_string_name(self):
        self.assertEqual(sp._type_name(0xFFFF), "STR")


class TestParseExtDevicePropRecordNone(unittest.TestCase):
    def test_decodes_current_and_default(self):
        data = build_none_record(code=0xD211, dtype=0x0004, value=2)
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["code"], 0xD211)
        self.assertEqual(record["current"], 2)
        self.assertEqual(record["default"], 2)
        self.assertEqual(record["form"], sp.FORM_NONE)
        self.assertIsNone(record["range"])
        self.assertIsNone(record["enum"])
        self.assertEqual(end, len(data))

    def test_getset_and_enabled_flags(self):
        data = (
            _record_header(0x5013, 0x0004, getset=0, enabled=0)
            + _scalar(0x0004, 1) + _scalar(0x0004, 1) + bytes([0x00])
        )
        record, _ = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["getset"], "Get only")
        self.assertFalse(record["enabled"])

    def test_legacy_record_needs_single_enum_flag(self):
        data = build_none_record(code=0xD211, value=2, legacy=True)
        record, end = sp.parse_ext_device_prop_record(data, single_enum=True)
        self.assertEqual(record["current"], 2)
        self.assertEqual(end, len(data))


class TestParseExtDevicePropRecordRange(unittest.TestCase):
    def test_decodes_min_max_step(self):
        data = build_range_record(vmin=10, vmax=200, step=5, current=50)
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["form"], sp.FORM_RANGE)
        self.assertEqual(record["range"], {"min": 10, "max": 200, "step": 5})
        self.assertEqual(record["current"], 50)
        self.assertEqual(end, len(data))


class TestParseExtDevicePropRecordEnum(unittest.TestCase):
    """v300 default: every enum carries a Supported *and* an Available list,
    verified live against the A6700 - e.g. 0xD211 aspect_ratio decodes as
    Supported=[1,3,2,4], Available=[1,3,2,4], current=2 (see
    docs/BIONZ_XR_PTP_SDIO.md)."""

    def test_decodes_supported_and_available_by_default(self):
        data = build_enum_record(values=(1, 3, 2, 4), current=2,
                                  available=(1, 3, 2, 4))
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["form"], sp.FORM_ENUM)
        self.assertEqual(record["enum"], [1, 3, 2, 4])
        self.assertEqual(record["available"], [1, 3, 2, 4])
        self.assertEqual(record["current"], 2)
        self.assertEqual(end, len(data))

    def test_available_can_differ_from_supported(self):
        data = build_enum_record(values=(1, 2, 3, 4), available=(1, 2))
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["enum"], [1, 2, 3, 4])
        self.assertEqual(record["available"], [1, 2])
        self.assertEqual(end, len(data))

    def test_real_aspect_ratio_record_matches_live_capture(self):
        """Exact bytes decoded from a live 0x9209 capture for 0xD211,
        cross-referenced against the 0x9202 code list (21 bytes, zero
        leftover) - see docs/BIONZ_XR_PTP_SDIO.md."""
        data = bytes.fromhex("11d202000101000202040001030204040001030204")
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["code"], 0xD211)
        self.assertEqual(record["dtype_name"], "UINT8")
        self.assertEqual(record["current"], 2)
        self.assertEqual(record["enum"], [1, 3, 2, 4])
        self.assertEqual(record["available"], [1, 3, 2, 4])
        self.assertEqual(end, len(data))

    def test_legacy_single_list_has_no_available(self):
        data = build_enum_record(values=(1, 2, 3), current=3, legacy=True)
        record, end = sp.parse_ext_device_prop_record(data, single_enum=True)
        self.assertEqual(record["enum"], [1, 2, 3])
        self.assertIsNone(record["available"])
        self.assertEqual(end, len(data))


class TestParseExtDevicePropRecordArray(unittest.TestCase):
    def test_decodes_uint16_array(self):
        data = build_array_record(values=(10, 20, 30))
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["dtype_name"], "ARRAY<UINT16>")
        self.assertEqual(record["current"], [10, 20, 30])
        self.assertEqual(end, len(data))


class TestParseExtDevicePropRecordString(unittest.TestCase):
    def test_decodes_utf16_string(self):
        data = build_string_record(value="S-Log3")
        record, end = sp.parse_ext_device_prop_record(data)
        self.assertEqual(record["dtype_name"], "STR")
        self.assertEqual(record["current"], "S-Log3")
        self.assertEqual(end, len(data))


class TestParseExtDevicePropRecordErrors(unittest.TestCase):
    def test_truncated_header_raises(self):
        with self.assertRaises(sp.SdioDecodeError):
            sp.parse_ext_device_prop_record(b"\x01\x02")

    def test_unknown_dtype_raises(self):
        data = _record_header(0xD211, 0x1234, getset=1, enabled=1) + b"\x00" * 4
        with self.assertRaises(sp.SdioDecodeError):
            sp.parse_ext_device_prop_record(data)

    def test_unknown_form_flag_raises(self):
        data = (
            _record_header(0xD211, 0x0004, getset=1, enabled=1)
            + _scalar(0x0004, 1) + _scalar(0x0004, 1) + bytes([0x99])
        )
        with self.assertRaises(sp.SdioDecodeError):
            sp.parse_ext_device_prop_record(data)

    def test_truncated_available_list_count_raises(self):
        # A v300 enum whose Supported list is present but the stream cuts
        # off right before the Available list's count - should not be
        # mistaken for a complete record.
        data = (
            _record_header(0x5013, 0x0004, getset=1, enabled=1)
            + _scalar(0x0004, 1) + _scalar(0x0004, 2)
            + bytes([0x02]) + struct.pack("<H", 1) + _scalar(0x0004, 1)
        )
        with self.assertRaises(sp.SdioDecodeError):
            sp.parse_ext_device_prop_record(data)


class TestParseAllExtPropInfoStream(unittest.TestCase):
    def test_decodes_a_back_to_back_stream_of_mixed_records(self):
        stream = stream_header(5) + (
            build_none_record(code=0xD211, value=2)
            + build_range_record(code=0x500E, vmin=0, vmax=100, step=1, current=40)
            + build_enum_record(code=0x5013, values=(1, 2, 3), current=2)
            + build_array_record(code=0xD219, values=(1, 2))
            + build_string_record(code=0xD21D, value="Movie")
        )
        records = sp.parse_all_ext_prop_info(stream)
        self.assertEqual([r["code"] for r in records],
                         [0xD211, 0x500E, 0x5013, 0xD219, 0xD21D])
        self.assertEqual(records[0]["current"], 2)
        self.assertEqual(records[1]["range"]["max"], 100)
        self.assertEqual(records[2]["enum"], [1, 2, 3])
        self.assertEqual(records[2]["available"], [1, 2, 3])
        self.assertEqual(records[3]["current"], [1, 2])
        self.assertEqual(records[4]["current"], "Movie")

    def test_stops_cleanly_on_a_trailing_garbage_tail(self):
        stream = stream_header(1) + build_none_record(code=0xD211, value=1) + b"\xFF\xFF\xFF"
        records = sp.parse_all_ext_prop_info(stream)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], 0xD211)

    def test_empty_stream_decodes_to_no_records(self):
        self.assertEqual(sp.parse_all_ext_prop_info(b""), [])

    def test_header_too_short_decodes_to_no_records(self):
        self.assertEqual(sp.parse_all_ext_prop_info(b"\x01\x02\x03"), [])

    def test_legacy_stream_has_no_header_and_single_lists(self):
        stream = (
            build_none_record(code=0xD211, value=1, legacy=True)
            + build_enum_record(code=0x5013, values=(1, 2), current=1, legacy=True)
        )
        records = sp.parse_all_ext_prop_info(stream, single_enum=True)
        self.assertEqual([r["code"] for r in records], [0xD211, 0x5013])
        self.assertIsNone(records[1]["available"])

    def test_v300_decoder_fails_on_a_legacy_stream(self):
        """Feeding a v200-shaped (legacy) stream to the v300 default decoder
        should not silently decode garbage - the missing stream header and
        extra padding byte should misalign it quickly."""
        stream = build_none_record(code=0xD211, value=1, legacy=True)
        records = sp.parse_all_ext_prop_info(stream)  # default: v300
        self.assertEqual(records, [])


class TestRecordsToJson(unittest.TestCase):
    def test_keys_are_hex_coded(self):
        records = sp.parse_all_ext_prop_info(
            stream_header(1) + build_none_record(code=0xD211, value=1)
        )
        out = sp.records_to_json(records)
        self.assertIn("0xD211", out)
        self.assertEqual(out["0xD211"]["current"], 1)


class TestParseBinCliOfflineRoundTrip(unittest.TestCase):
    """--parse-bin needs no camera: dump synthetic bytes to a temp file and
    decode + export JSON exactly like the CLI does."""

    def test_parse_bin_then_json_round_trips(self):
        stream = stream_header(2) + (
            build_none_record(code=0xD211, value=1)
            + build_enum_record(code=0x5013, values=(1, 2), current=1)
        )
        with tempfile.TemporaryDirectory() as tmp:
            bin_path = os.path.join(tmp, "dump.bin")
            json_path = os.path.join(tmp, "out.json")
            with open(bin_path, "wb") as fh:
                fh.write(stream)

            with open(bin_path, "rb") as fh:
                raw = fh.read()
            records = sp.parse_all_ext_prop_info(raw)
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(sp.records_to_json(records), fh)

            with open(json_path, "r", encoding="utf-8") as fh:
                decoded = json.load(fh)
        self.assertIn("0xD211", decoded)
        self.assertIn("0x5013", decoded)
        self.assertEqual(decoded["0xD211"]["current"], 1)
        self.assertEqual(decoded["0x5013"]["enum"], [1, 2])
        self.assertEqual(decoded["0x5013"]["available"], [1, 2])

    def test_single_enum_round_trip_for_a_legacy_dump(self):
        stream = build_enum_record(code=0x5013, values=(1, 2), current=1, legacy=True)
        with tempfile.TemporaryDirectory() as tmp:
            bin_path = os.path.join(tmp, "legacy.bin")
            with open(bin_path, "wb") as fh:
                fh.write(stream)
            with open(bin_path, "rb") as fh:
                raw = fh.read()
            records = sp.parse_all_ext_prop_info(raw, single_enum=True)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["available"])


class TestDeviceInfoParsingReuse(unittest.TestCase):
    """sdio_probe re-exports parse_device_info from probe_a6700 rather than
    duplicating it - a synthetic GetDeviceInfo dataset should decode the
    same way through either import path."""

    def test_parses_a_synthetic_device_info_dataset(self):
        data = (
            struct.pack("<HIH", 100, 0x00000011, 0x0012C)
            + _ptp_string("Sony Corp.")
            + struct.pack("<H", 0)  # functional mode
            + _u16_array([0x1001, 0x1002, 0x9201, 0x9209])
            + _u16_array([0xC201])
            + _u16_array([0xD211, 0xD241])
            + _u16_array([])
            + _u16_array([])
            + _ptp_string("Sony Corp.")
            + _ptp_string("ILCE-6700")
            + _ptp_string("2.00")
            + _ptp_string("")
        )
        info = parse_device_info(data)
        self.assertEqual(info["model"], "ILCE-6700")
        self.assertEqual(info["device_version"], "2.00")
        self.assertIn(0x9201, info["operations_supported"])


if __name__ == "__main__":
    unittest.main()
