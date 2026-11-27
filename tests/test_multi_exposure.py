#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the 16-bit linear RAW multi-exposure blender in
multi_exposure.py (blend_raw16). Pure numpy math on synthetic uint16 arrays -
no rawpy, no tifffile, no real .ARW file needed.

Run from the repo root:  python -m unittest -v tests.test_multi_exposure
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

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


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestComposeGhostPreview(unittest.TestCase):
    def setUp(self):
        self.captured = np.full((2, 2, 3), 100, dtype=np.uint8)
        self.live = np.full((2, 2, 3), 40, dtype=np.uint8)

    def test_blends_captured_and_live_frames_by_mode(self):
        expected = {
            "dark": 40,
            "bright": 100,
            "avg": 70,
            "add": 140,
        }
        for mode, value in expected.items():
            with self.subTest(mode=mode):
                out = me.compose_ghost_preview(self.live, [self.captured], mode)
                self.assertEqual(out.dtype, np.uint8)
                self.assertTrue(np.all(out == value))

    def test_clamps_additive_preview_to_dtype_range(self):
        bright = np.full((2, 2, 3), 200, dtype=np.uint8)
        out = me.compose_ghost_preview(bright, [bright], "add")
        self.assertTrue(np.all(out == 255))

    def test_returns_copy_when_no_frame_has_been_captured(self):
        out = me.compose_ghost_preview(self.live, [], "avg")
        self.assertTrue(np.array_equal(out, self.live))
        self.assertIsNot(out, self.live)

    def test_rejects_mismatched_shapes(self):
        other = np.zeros((3, 3, 3), dtype=np.uint8)
        with self.assertRaises(ValueError):
            me.compose_ghost_preview(self.live, [other], "avg")

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            me.compose_ghost_preview(self.live, [self.captured], "screen")


class TestRawBlendCLI(unittest.TestCase):
    def run_cli(self, *args):
        with mock.patch.object(sys, "argv", ["multi_exposure.py", *args]):
            me.main()

    def test_blends_arw_inputs_to_output_with_selected_mode(self):
        with mock.patch.object(me, "blend_raw_files", return_value=True) as blend:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.ARW", "two.arw", "-o", "merged.tiff",
                             "--mode", "bright")
        self.assertEqual(exc.exception.code, 0)
        blend.assert_called_once_with(["one.ARW", "two.arw"], "merged.tiff", mode="bright")

    def test_defaults_raw_mode_to_avg(self):
        with mock.patch.object(me, "blend_raw_files", return_value=True) as blend:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.arw", "two.arw", "--output", "merged.tiff")
        self.assertEqual(exc.exception.code, 0)
        blend.assert_called_once_with(["one.arw", "two.arw"], "merged.tiff", mode="avg")

    def test_returns_failure_when_blend_fails(self):
        with mock.patch.object(me, "blend_raw_files", return_value=False):
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.arw", "two.arw", "-o", "merged.tiff")
        self.assertEqual(exc.exception.code, 1)

    def test_requires_two_to_nine_arw_files(self):
        for paths in (["one.arw"], ["frame.arw"] * 10):
            with self.subTest(count=len(paths)):
                args = ["--raw-blend", *paths, "-o", "merged.tiff"]
                with mock.patch.object(me, "blend_raw_files") as blend:
                    with self.assertRaises(SystemExit) as exc:
                        self.run_cli(*args)
                self.assertEqual(exc.exception.code, 2)
                blend.assert_not_called()

    def test_rejects_non_arw_input(self):
        with mock.patch.object(me, "blend_raw_files") as blend:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.jpg", "two.arw", "-o", "merged.tiff")
        self.assertEqual(exc.exception.code, 2)
        blend.assert_not_called()

    def test_requires_tiff_output(self):
        with mock.patch.object(me, "blend_raw_files") as blend:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.arw", "two.arw", "-o", "merged.png")
        self.assertEqual(exc.exception.code, 2)
        blend.assert_not_called()

    def test_requires_output_for_raw_blend(self):
        with mock.patch.object(me, "blend_raw_files") as blend:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--raw-blend", "one.arw", "two.arw")
        self.assertEqual(exc.exception.code, 2)
        blend.assert_not_called()

    def test_rejects_raw_options_without_raw_blend(self):
        for args in (("--mode", "avg"), ("--output", "merged.tiff")):
            with self.subTest(args=args):
                with self.assertRaises(SystemExit) as exc:
                    self.run_cli(*args)
                self.assertEqual(exc.exception.code, 2)


class TestLiveGhostCLI(unittest.TestCase):
    def run_cli(self, *args):
        with mock.patch.object(sys, "argv", ["multi_exposure.py", *args]):
            me.main()

    def test_runs_live_ghost_with_selected_options(self):
        with mock.patch.object(me, "live_ghost", return_value=True) as ghost:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--live-ghost", "--source", "0", "--shots", "5",
                             "--mode", "bright")
        self.assertEqual(exc.exception.code, 0)
        ghost.assert_called_once_with("0", 5, "bright")

    def test_defaults_to_webcam_and_average_mode(self):
        with mock.patch.object(me, "live_ghost", return_value=True) as ghost:
            with self.assertRaises(SystemExit) as exc:
                self.run_cli("--live-ghost", "--shots", "2")
        self.assertEqual(exc.exception.code, 0)
        ghost.assert_called_once_with("0", 2, "avg")

    def test_requires_two_to_nine_shots(self):
        for shots in ("1", "10"):
            with self.subTest(shots=shots):
                with mock.patch.object(me, "live_ghost") as ghost:
                    with self.assertRaises(SystemExit) as exc:
                        self.run_cli("--live-ghost", "--shots", shots)
                self.assertEqual(exc.exception.code, 2)
                ghost.assert_not_called()

    def test_rejects_source_without_live_ghost(self):
        with self.assertRaises(SystemExit) as exc:
            self.run_cli("--source", "clip.mp4")
        self.assertEqual(exc.exception.code, 2)


class TestLiveGhostDependencies(unittest.TestCase):
    def test_missing_opencv_returns_clear_install_message(self):
        output = io.StringIO()
        with mock.patch.dict(sys.modules, {"cv2": None}), contextlib.redirect_stdout(output):
            ok = me.live_ghost("0", 2, "avg")
        self.assertFalse(ok)
        self.assertIn("pip install opencv-python", output.getvalue())


if __name__ == "__main__":
    unittest.main()
