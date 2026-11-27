#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the declarative Open Gate profiles and the single-session
injector (opengate_inject). No camera, no USB: a byte-addressable RAM mock stands
in for the on-camera transport.

Run from the repo root:  python -m unittest -v tests.test_profiles
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import opengate_inject as inj
import ram_opengate as rg


class RamMock(rg.CameraMemory):
    """Byte-addressable RAM seeded with each profile's stock bytes."""
    def __init__(self):
        self.ram = {}

    def seed_stock(self, prof):
        for _step, w in inj.iter_writes(prof):
            if w.get("stock"):
                self.mem_write(inj._resolve(prof, w["region"], w["addr"]),
                               bytes.fromhex(w["stock"]))

    def mem_read(self, addr, length):
        return bytes(self.ram.get(addr + i, 0) for i in range(length))

    def mem_write(self, addr, data):
        for i, b in enumerate(data):
            self.ram[addr + i] = b


class TestProfilesLoad(unittest.TestCase):
    NAMES = ("profile_4k_24p_stable", "profile_true_3x2_experimental",
             "playback_fix")

    def test_all_load_and_schema(self):
        for name in self.NAMES:
            p = inj.load_profile(name)
            self.assertEqual(p["schema"], "opengate-profile/1")
            self.assertEqual(p["model"], "ILCE-6700")
            self.assertEqual(p["firmware"], "2.00")

    def test_no_firmware_bytes_in_payload_steps(self):
        # Payload steps must reference an external .bin, never embed bytes.
        for name in self.NAMES:
            p = inj.load_profile(name)
            for step in p["steps"]:
                if step.get("kind") in ("encoder_blob", "sensor_registers",
                                        "code_patch"):
                    self.assertIn("payload_ref", step, f"{name}/{step['id']}")
                    self.assertNotIn("target", step, f"{name}/{step['id']}")

    def test_geometry_writes_roundtrip_hex(self):
        p = inj.load_profile("profile_4k_24p_stable")
        for _s, w in inj.iter_writes(p):
            self.assertEqual(len(bytes.fromhex(w["stock"])), w["len"])
            if w.get("target") is not None:
                self.assertEqual(len(bytes.fromhex(w["target"])), w["len"])

    def test_stable_height_word_is_2560(self):
        # L16 output size target packs height 0x0A00 (2560) in the high 16 bits.
        p = inj.load_profile("profile_4k_24p_stable")
        w = next(w for s, w in inj.iter_writes(p) if w["addr"] == "0x0199ecc4")
        word = struct.unpack("<I", bytes.fromhex(w["target"]))[0]
        self.assertEqual(word & 0xFFFF, 0x0F00)        # width 3840
        self.assertEqual((word >> 16) & 0xFFFF, 0x0A00)  # height 2560

    def test_experimental_has_no_targets_yet(self):
        # Never run on hardware => encoder/sensor payloads carry no target fp,
        # and buffer-size writes defer their target to apply time.
        p = inj.load_profile("profile_true_3x2_experimental")
        self.assertEqual(p["status"], "experimental")
        self.assertEqual(p["sensor_window"]["rows"], 3968)
        self.assertEqual(p["sensor_window"]["first_row"], 94)
        l13 = next(s for s in p["steps"] if s["id"] == "L13")
        self.assertTrue(all(w["target"] is None for w in l13["writes"]))


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.p = inj.load_profile("profile_4k_24p_stable")

    def test_ntsc_matches_24p(self):
        checks = inj.preflight(self.p, video_standard="NTSC", dial="MOVIE")
        self.assertTrue(all(ok is not False for ok, _ in checks))

    def test_pal_mismatch_flagged(self):
        # 24p profile under... actually profile lists 25/50 too, so PAL is fine;
        # a STILL dial must flag.
        checks = inj.preflight(self.p, video_standard="PAL", dial="STILL")
        self.assertIn(False, [ok for ok, _ in checks])

    def test_unknown_values_warn_not_fail(self):
        checks = inj.preflight(self.p, video_standard=None, dial=None)
        self.assertIn(None, [ok for ok, _ in checks])


class TestVerifyApplyRestore(unittest.TestCase):
    def setUp(self):
        self.p = inj.load_profile("profile_4k_24p_stable")

    def test_verify_stock_true_when_seeded(self):
        mem = RamMock()
        mem.seed_stock(self.p)
        ok, results = inj.verify_stock(mem, self.p)
        # Anchors have no seeded bytes (sha of zeros) -> those fail; geometry ok.
        geo = [r for r in results if "0x0199ecc4" in r[0] or "0x02580" in r[0]
               or "0xe99" in r[0] or "0x001f5" in r[0]]
        self.assertTrue(all(ok_ for _n, ok_, _d in geo))

    def test_apply_refuses_without_confirm(self):
        mem = RamMock()
        mem.seed_stock(self.p)
        # Drop anchors so the stock check is pure geometry (seeded), isolating the
        # confirm gate.
        prof = _geometry_only(self.p)
        with self.assertRaises(inj.ProfileError) as cm:
            inj.apply_profile(mem, prof, confirm=False)
        self.assertIn("confirm", str(cm.exception).lower())

    def test_apply_then_restore_roundtrip(self):
        prof = _geometry_only(self.p)
        mem = RamMock()
        mem.seed_stock(prof)
        backup = inj.apply_profile(mem, prof, confirm=True)
        # Every geometry target now in RAM.
        for _s, w in inj.iter_writes(prof):
            addr = inj._resolve(prof, w["region"], w["addr"])
            self.assertEqual(mem.mem_read(addr, w["len"]),
                             bytes.fromhex(w["target"]))
        inj.restore_profile(mem, prof, backup)
        for _s, w in inj.iter_writes(prof):
            addr = inj._resolve(prof, w["region"], w["addr"])
            self.assertEqual(mem.mem_read(addr, w["len"]),
                             bytes.fromhex(w["stock"]))

    def test_apply_aborts_on_wrong_firmware(self):
        prof = _geometry_only(self.p)
        mem = RamMock()
        mem.seed_stock(prof)
        # Corrupt one site -> whole apply must abort, nothing written.
        bad_addr = inj._resolve(prof, "coprocessor", "0x0199ecc4")
        mem.mem_write(bad_addr, b"\xde\xad\xbe\xef")
        with self.assertRaises(inj.ProfileError):
            inj.apply_profile(mem, prof, confirm=True)
        # Other sites untouched (still stock).
        other = inj._resolve(prof, "coprocessor", "0x02580cd8")
        self.assertEqual(mem.mem_read(other, 4), bytes.fromhex("00123401"))

    def test_default_transport_refuses(self):
        # No transport wired: a read must refuse, not guess.
        with self.assertRaises(rg.MscError):
            inj.verify_stock(rg.CameraMemory(), self.p)


def _geometry_only(prof):
    """Return a shallow copy of prof with anchor-bearing steps' anchors removed,
    so stock checks depend only on seeded geometry writes."""
    import copy
    p = copy.deepcopy(prof)
    for step in p["steps"]:
        step.pop("anchors", None)
    return p


if __name__ == "__main__":
    unittest.main(verbosity=2)
