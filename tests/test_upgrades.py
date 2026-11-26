#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the Fujifilm multi-exposure modes and the ram_opengate
signature scanner / MSC probe. No real camera and no usb traffic: the SCSI
device is a plain in-memory stub and images are tiny generated PNGs.

Run from the repo root:  python -m unittest -v tests.test_upgrades
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import numpy as np
    from PIL import Image
    HAVE_IMG = True
except ImportError:
    HAVE_IMG = False

import multi_exposure as me
import ram_opengate as rg


# ---------------------------------------------------------------------------
# Task 1: Fujifilm stack modes
# ---------------------------------------------------------------------------
@unittest.skipUnless(HAVE_IMG, "numpy/Pillow required")
class TestStackModes(unittest.TestCase):
    def setUp(self):
        self.f1 = np.full((2, 2, 3), 100.0, dtype=np.float32)
        self.f2 = np.full((2, 2, 3), 150.0, dtype=np.float32)
        self.frames = [self.f1, self.f2]

    def test_additive_clips(self):
        hi = [np.full((2, 2, 3), 200.0, np.float32),
              np.full((2, 2, 3), 100.0, np.float32)]
        out = me._blend(hi, "additive", 255.0)
        self.assertTrue(np.all(out == 255.0))          # 300 -> clipped to 255

    def test_additive_sum(self):
        out = me._blend(self.frames, "additive", 255.0)
        self.assertTrue(np.all(out == 250.0))          # 100 + 150

    def test_average(self):
        out = me._blend(self.frames, "average", 255.0)
        self.assertTrue(np.all(out == 125.0))

    def test_bright_is_max(self):
        out = me._blend(self.frames, "bright", 255.0)
        self.assertTrue(np.all(out == 150.0))

    def test_dark_is_min(self):
        out = me._blend(self.frames, "dark", 255.0)
        self.assertTrue(np.all(out == 100.0))

    def test_aliases(self):
        self.assertEqual(me._norm_mode("lighten"), "bright")
        self.assertEqual(me._norm_mode("darken"), "dark")
        a = me._blend(self.frames, "lighten", 255.0)
        b = me._blend(self.frames, "bright", 255.0)
        self.assertTrue(np.array_equal(a, b))


@unittest.skipUnless(HAVE_IMG, "numpy/Pillow required")
class TestStackFiles(unittest.TestCase):
    def _write(self, d, name, rgb):
        p = os.path.join(d, name)
        Image.fromarray(np.full((4, 4, 3), rgb, dtype=np.uint8)).save(p)
        return p

    def test_stack_images_each_mode(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "a.png", (10, 20, 30))
            self._write(d, "b.png", (40, 60, 80))
            paths = sorted([os.path.join(d, "a.png"), os.path.join(d, "b.png")])
            expect = {"average": (25, 40, 55), "bright": (40, 60, 80),
                      "dark": (10, 20, 30), "additive": (50, 80, 110)}
            for mode, px in expect.items():
                out = os.path.join(d, f"out_{mode}.png")
                self.assertTrue(me.stack_images(paths, out, mode=mode))
                got = tuple(np.asarray(Image.open(out).convert("RGB"))[0, 0])
                self.assertEqual(got, px, mode)

    def test_stack_all_modes(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "a.png", (10, 20, 30))
            self._write(d, "b.png", (40, 60, 80))
            paths = [os.path.join(d, "a.png"), os.path.join(d, "b.png")]
            outs = me.stack_all_modes(paths, os.path.join(d, "stk.png"))
            self.assertEqual(len(outs), 4)
            for m in me.CORE_MODES:
                self.assertTrue(os.path.exists(os.path.join(d, f"stk_{m}.png")), m)


# ---------------------------------------------------------------------------
# Task 2: ARM64 signature scanner + MSC probe
# ---------------------------------------------------------------------------
def _movz(imm16, rd=0):
    """Encode 'movz w<rd>, #imm16, lsl #0' (little-endian 4-byte word)."""
    return (rg.MOVZ_LSL0_BASE | ((imm16 & 0xFFFF) << 5) | (rd & 0x1F))


class FakeScsi:
    """In-memory SCSI stub: serves mem_read from a buffer and canned INQUIRY."""
    def __init__(self, base=0, buf=b""):
        self.base, self.buf = base, buf

    def mem_read(self, addr, length):
        off = addr - self.base
        return self.buf[off:off + length]

    def inquiry(self):
        data = (bytes([0x00, 0x80, 0x05, 0x02, 31, 0, 0, 0])
                + b"Sony    " + b"Camera Storage  " + b"1.00")
        return 0, data

    def test_unit_ready(self):
        return 1, b""                      # not ready / no medium (normal)

    def read_capacity10(self):
        return 0, struct.pack(">II", 2047, 512)


class MockMem(rg.CameraMemory):
    """Byte-addressable RAM mock for verify/patch/restore round-trips."""
    def __init__(self):
        self.ram = {}

    def seed(self, addr, value16):
        self.mem_write(addr, struct.pack("<H", value16))

    def mem_read(self, addr, length):
        return bytes(self.ram.get(addr + i, 0) for i in range(length))

    def mem_write(self, addr, data):
        for i, b in enumerate(data):
            self.ram[addr + i] = b


class TestSignatureScanner(unittest.TestCase):
    def test_is_movz(self):
        self.assertTrue(rg._is_movz_imm(_movz(0x0870, 2), 0x0870))
        self.assertTrue(rg._is_movz_imm(_movz(0x0F00, 5), 0x0F00))
        self.assertFalse(rg._is_movz_imm(0xD503201F, 0x0870))   # NOP, not movz
        self.assertFalse(rg._is_movz_imm(_movz(0x0870, 2), 0x0F00))

    def _buf(self, with_width=True):
        words = [0xD503201F] * 64                      # NOPs
        words[12] = _movz(rg.OPENGATE_WIDTH, 1) if with_width else 0xD503201F
        words[16] = _movz(rg.STOCK_HEIGHT, 2)          # height store
        return b"".join(struct.pack("<I", w) for w in words)

    def test_finds_height_near_width(self):
        base = 0x1000
        dev = FakeScsi(base, self._buf(with_width=True))
        site = rg.find_libmpr_height_site(dev, base, len(dev.buf))
        self.assertEqual(site, base + 16 * 4)          # offset of the height word

    def test_none_without_width(self):
        base = 0x1000
        dev = FakeScsi(base, self._buf(with_width=False))
        self.assertIsNone(rg.find_libmpr_height_site(dev, base, len(dev.buf)))

    def test_requires_scan_range(self):
        with self.assertRaises(rg.MscError):
            rg.find_libmpr_height_site(FakeScsi(), None, None)


class TestMscProbe(unittest.TestCase):
    def test_probe_reports_responsive(self):
        self.assertTrue(rg.probe_msc(FakeScsi()))

    def test_default_transport_refuses(self):
        # The MIT build ships no RAM transport: read/write must refuse, not guess.
        with self.assertRaises(rg.MscError):
            rg.CameraMemory().mem_read(0x1000, 2)
        with self.assertRaises(rg.MscError):
            rg.CameraMemory().mem_write(0x1000, b"\x00\x00")


class TestVerifyPatchRestore(unittest.TestCase):
    def _seeded(self, value=rg.STOCK_HEIGHT):
        mem = MockMem()
        for name in rg.HEIGHT_SITES:
            mem.seed(rg.A6700_200_SITES[name], value)
        return mem

    def test_verify_reports_stock(self):
        rows = rg.verify_sites(self._seeded())
        self.assertTrue(all(lab == "stock 2160" for _, _, _, lab in rows))

    def test_patch_then_restore(self):
        mem = self._seeded()
        bak = rg.patch_sites(mem, 0, rg.OPENGATE_HEIGHT, expect=rg.STOCK_HEIGHT)
        self.assertEqual(len(bak), len(rg.HEIGHT_SITES))
        self.assertTrue(all(lab == "open-gate 2560"
                            for _, _, _, lab in rg.verify_sites(mem)))
        rg.patch_sites(mem, 0, rg.STOCK_HEIGHT)          # restore
        self.assertTrue(all(lab == "stock 2160"
                            for _, _, _, lab in rg.verify_sites(mem)))

    def test_patch_aborts_on_wrong_firmware(self):
        mem = self._seeded(value=0x1234)                 # unexpected bytes
        with self.assertRaises(rg.MscError):
            rg.patch_sites(mem, 0, rg.OPENGATE_HEIGHT, expect=rg.STOCK_HEIGHT)
        # aborted before any write: sites untouched
        self.assertEqual(rg.read_height(mem, rg.A6700_200_SITES[rg.HEIGHT_SITES[0]]),
                         0x1234)


if __name__ == "__main__":
    unittest.main(verbosity=2)
