#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the 16-bit linear RAW multi-exposure blender in
multi_exposure.py (blend_raw16). Pure numpy math on synthetic uint16 arrays -
no rawpy, no tifffile, no real .ARW file needed.

Run from the repo root:  python -m unittest -v tests.test_multi_exposure
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

import multi_exposure as me


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestBlendRaw16Modes(unittest.TestCase):
    def setUp(self):
        # Three 2x2x3 "frames" of flat colors, well inside uint16 range.
        self.f_low = np.full((2, 2, 3), 1000, dtype=np.uint16)
        self.f_mid = np.full((2, 2, 3), 20000, dtype=np.uint16)
        self.f_high = np.full((2, 2, 3), 40000, dtype=np.uint16)
        self.frames3 = [self.f_low, self.f_mid, self.f_high]

    def test_dark_is_per_pixel_minimum(self):
        out = me.blend_raw16(self.frames3, "dark")
        self.assertEqual(out.dtype, np.uint16)
        self.assertTrue(np.all(out == 1000))

    def test_bright_is_per_pixel_maximum(self):
        out = me.blend_raw16(self.frames3, "bright")
        self.assertTrue(np.all(out == 40000))

    def test_avg_is_per_pixel_mean(self):
        out = me.blend_raw16(self.frames3, "avg")
        want = round((1000 + 20000 + 40000) / 3)
        self.assertTrue(np.all(out == want))

    def test_add_sums_without_clipping_when_in_range(self):
        two = [self.f_low, self.f_mid]
        out = me.blend_raw16(two, "add")
        self.assertTrue(np.all(out == 21000))

    def test_add_clamps_at_65535(self):
        hi = [np.full((2, 2, 3), 40000, dtype=np.uint16),
              np.full((2, 2, 3), 40000, dtype=np.uint16)]  # sum = 80000
        out = me.blend_raw16(hi, "add")
        self.assertTrue(np.all(out == 65535))

    def test_modes_differ_on_varying_pixels(self):
        # Per-pixel values differ across the frame so min/max/mean/sum are all
        # distinguishable at once, not just the flat-color case above.
        a = np.array([[[10, 10, 10], [100, 100, 100]],
                      [[10, 10, 10], [100, 100, 100]]], dtype=np.uint16)
        b = np.array([[[50, 50, 50], [20, 20, 20]],
                      [[50, 50, 50], [20, 20, 20]]], dtype=np.uint16)
        dark = me.blend_raw16([a, b], "dark")
        bright = me.blend_raw16([a, b], "bright")
        avg = me.blend_raw16([a, b], "avg")
        add = me.blend_raw16([a, b], "add")
        self.assertTrue(np.array_equal(dark[0, 0], [10, 10, 10]))
        self.assertTrue(np.array_equal(dark[0, 1], [20, 20, 20]))
        self.assertTrue(np.array_equal(bright[0, 0], [50, 50, 50]))
        self.assertTrue(np.array_equal(bright[0, 1], [100, 100, 100]))
        self.assertTrue(np.array_equal(avg[0, 0], [30, 30, 30]))
        self.assertTrue(np.array_equal(avg[0, 1], [60, 60, 60]))
        self.assertTrue(np.array_equal(add[0, 0], [60, 60, 60]))
        self.assertTrue(np.array_equal(add[0, 1], [120, 120, 120]))

    def test_accepts_full_2_to_9_frame_range(self):
        for n in range(2, 10):
            frames = [np.full((2, 2, 3), 1000 * i, dtype=np.uint16) for i in range(1, n + 1)]
            out = me.blend_raw16(frames, "avg")
            self.assertEqual(out.shape, (2, 2, 3))

    def test_rejects_too_few_frames(self):
        with self.assertRaises(ValueError):
            me.blend_raw16([self.f_low], "avg")

    def test_rejects_too_many_frames(self):
        frames = [self.f_low] * 10
        with self.assertRaises(ValueError):
            me.blend_raw16(frames, "avg")

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            me.blend_raw16(self.frames3, "screen")

    def test_rejects_mismatched_shapes(self):
        other_shape = np.full((3, 3, 3), 1000, dtype=np.uint16)
        with self.assertRaises(ValueError):
            me.blend_raw16([self.f_low, other_shape], "avg")


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestBlendRawFilesGuards(unittest.TestCase):
    """blend_raw_files() is the file-I/O wrapper (rawpy + tifffile); these only
    check its own argument guards, which run before touching either."""

    def test_rejects_too_few_paths_without_touching_rawpy(self):
        self.assertFalse(me.blend_raw_files(["one.arw"], "out.tiff", mode="avg"))

    def test_rejects_too_many_paths_without_touching_rawpy(self):
        self.assertFalse(me.blend_raw_files(["a.arw"] * 10, "out.tiff", mode="avg"))

    def test_rejects_unknown_mode_without_touching_rawpy(self):
        self.assertFalse(me.blend_raw_files(["a.arw", "b.arw"], "out.tiff", mode="screen"))


if __name__ == "__main__":
    unittest.main()
