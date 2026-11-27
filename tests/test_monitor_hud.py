#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for monitor_hud.py's pure logic: multi-aspect crop box math,
mode-switch command dispatch, and waveform generation. No cv2, no real
subprocess, no camera - the HUD's rendering/interactive loop is a thin layer
over these, same split as multi_exposure.py's live_ghost().

Run from the repo root:  python -m unittest -v tests.test_monitor_hud
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

import monitor_hud as hud


class TestCropBoxMath(unittest.TestCase):
    """3:2 / 16:9 / 9:16 crop boxes on the verified A6700 Open Gate frame
    (3840x2560) land on the project's own known numbers (3840x2160 stock
    16:9, 1440x2560 vertical) - not arbitrary math."""

    def test_3x2_is_the_full_frame_uncropped(self):
        self.assertEqual(hud.crop_box_3x2(3840, 2560), (0, 0, 3840, 2560))

    def test_16x9_matches_the_stock_3840x2160_resolution(self):
        x, y, w, h = hud.crop_box_16x9(3840, 2560)
        self.assertEqual((w, h), (3840, 2160))
        self.assertEqual(x, 0)  # full width kept
        self.assertEqual(y, (2560 - 2160) // 2)  # centered vertically

    def test_9x16_matches_1440x2560_vertical(self):
        x, y, w, h = hud.crop_box_9x16(3840, 2560)
        self.assertEqual((w, h), (1440, 2560))
        self.assertEqual(y, 0)  # full height kept
        self.assertEqual(x, (3840 - 1440) // 2)  # centered horizontally

    def test_16x9_box_is_fully_inside_the_frame(self):
        w, h = 3840, 2560
        x, y, bw, bh = hud.crop_box_16x9(w, h)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + bw, w)
        self.assertLessEqual(y + bh, h)

    def test_9x16_box_is_fully_inside_the_frame(self):
        w, h = 3840, 2560
        x, y, bw, bh = hud.crop_box_9x16(w, h)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + bw, w)
        self.assertLessEqual(y + bh, h)

    def test_crop_boxes_scale_with_a_smaller_demo_frame(self):
        # --demo runs at a smaller resolution; the same 3:2 math must still
        # hold proportionally, not just at the exact 3840x2560 numbers.
        w, h = 960, 640  # also 3:2
        _, _, bw, bh = hud.crop_box_16x9(w, h)
        self.assertEqual((bw, bh), (960, 540))  # 960 * 9/16 = 540
        _, _, bw2, bh2 = hud.crop_box_9x16(w, h)
        self.assertEqual((bw2, bh2), (360, 640))  # 640 * 9/16 = 360


class TestGuideAndBlendModeCycling(unittest.TestCase):
    def test_guide_mode_cycles_all_four_in_order_and_wraps(self):
        seq = [hud.GUIDE_MODES[0]]
        for _ in range(len(hud.GUIDE_MODES)):
            seq.append(hud.cycle_guide_mode(seq[-1]))
        self.assertEqual(seq, ["all", "16:9", "9:16", "off", "all"])

    def test_guide_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            hud.cycle_guide_mode("4:3")

    def test_blend_mode_cycles_through_all_raw_blend_modes_and_wraps(self):
        import multi_exposure as me
        seq = [me.RAW_BLEND_MODES[0]]
        for _ in range(len(me.RAW_BLEND_MODES)):
            seq.append(hud.cycle_blend_mode(seq[-1]))
        self.assertEqual(seq[-1], seq[0])  # wrapped back to the start
        self.assertEqual(set(seq[:-1]), set(me.RAW_BLEND_MODES))

    def test_blend_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            hud.cycle_blend_mode("screen")


class TestModeCommandDispatch(unittest.TestCase):
    """build_mode_command() is pure - never runs anything - so these check
    exact argv construction and the safety refusals directly."""

    def test_demo_is_always_a_dry_run_plan_regardless_of_mode(self):
        cmd = hud.build_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=True)
        self.assertEqual(cmd, ["opengate-rs.exe", hud.DEFAULT_PROFILE, "--plan"])
        cmd2 = hud.build_mode_command("opengate-rs.exe", hud.MODE_STOCK, demo=True, confirm=True)
        self.assertEqual(cmd2, ["opengate-rs.exe", hud.DEFAULT_PROFILE, "--plan"])

    def test_live_stock_has_no_software_restore_command(self):
        cmd = hud.build_mode_command("opengate-rs.exe", hud.MODE_STOCK, demo=False)
        self.assertIsNone(cmd)

    def test_live_open_gate_without_confirm_is_refused(self):
        with self.assertRaises(PermissionError):
            hud.build_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=False, confirm=False)

    def test_live_open_gate_with_confirm_uses_the_real_confirm_ram_write_flag(self):
        cmd = hud.build_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=False, confirm=True)
        self.assertEqual(cmd, ["opengate-rs.exe", hud.DEFAULT_PROFILE, "--confirm-ram-write"])

    def test_custom_exe_path_and_profile_are_honored(self):
        cmd = hud.build_mode_command(
            "/custom/path/opengate-rs", hud.MODE_OPEN_GATE, demo=False, confirm=True,
            profile="fx30_v5.00")
        self.assertEqual(cmd, ["/custom/path/opengate-rs", "fx30_v5.00", "--confirm-ram-write"])

    def test_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            hud.build_mode_command("opengate-rs.exe", "bogus-mode")


class TestStatusPill(unittest.TestCase):
    def test_formats_demo_source(self):
        text = hud.format_status_pill("STOCK 16:9", "profile_4k_24p_stable", True)
        self.assertIn("STOCK 16:9", text)
        self.assertIn("profile_4k_24p_stable", text)
        self.assertIn("DEMO", text)

    def test_formats_live_usb_source(self):
        text = hud.format_status_pill("PATCHED 3:2", "profile_4k_24p_stable", False)
        self.assertIn("PATCHED 3:2", text)
        self.assertIn("LIVE USB", text)

    def test_rejects_unknown_ram_state(self):
        with self.assertRaises(ValueError):
            hud.format_status_pill("UNKNOWN", "p", True)


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestIreToRow(unittest.TestCase):
    def test_100_ire_is_the_top_row(self):
        self.assertEqual(hud.ire_to_row(100.0, 100), 0)

    def test_0_ire_is_the_bottom_row(self):
        self.assertEqual(hud.ire_to_row(0.0, 100), 99)

    def test_slog3_clip_marker_is_near_the_top(self):
        row = hud.ire_to_row(hud.SLOG3_CLIP_IRE, 100)
        self.assertLess(row, 10)  # 94 IRE should land close to the top row

    def test_clamps_out_of_range_values(self):
        self.assertEqual(hud.ire_to_row(150.0, 100), hud.ire_to_row(100.0, 100))
        self.assertEqual(hud.ire_to_row(-50.0, 100), hud.ire_to_row(0.0, 100))


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestLumaWaveform(unittest.TestCase):
    def test_output_shape_and_dtype(self):
        frame = np.zeros((40, 60, 3), dtype=np.uint8)
        scope = hud.luma_waveform(frame, out_width=32, out_height=16)
        self.assertEqual(scope.shape, (16, 32))
        self.assertEqual(scope.dtype, np.uint8)

    def test_all_white_frame_lights_up_the_top_row_everywhere(self):
        frame = np.full((10, 10, 3), 255, dtype=np.uint8)
        scope = hud.luma_waveform(frame, out_width=8, out_height=10)
        self.assertTrue(np.all(scope[0] > 0))      # top row (100 IRE) lit
        self.assertTrue(np.all(scope[1:] == 0))    # nothing anywhere else

    def test_all_black_frame_lights_up_the_bottom_row_everywhere(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        scope = hud.luma_waveform(frame, out_width=8, out_height=10)
        self.assertTrue(np.all(scope[-1] > 0))     # bottom row (0 IRE) lit
        self.assertTrue(np.all(scope[:-1] == 0))

    def test_upsampling_past_the_source_width_leaves_no_gap_columns(self):
        # Regression: a naive "which output bucket does this source column
        # land in" mapping leaves all-zero columns when out_width > src_w.
        frame = np.full((4, 4, 3), 255, dtype=np.uint8)
        scope = hud.luma_waveform(frame, out_width=8, out_height=10)
        self.assertTrue(np.all(scope[0] > 0), "every output column must be sampled")

    def test_left_right_split_frame_shows_up_on_the_correct_sides(self):
        frame = np.zeros((10, 300, 3), dtype=np.uint8)
        frame[:, :150] = 0      # left half: black -> bottom row
        frame[:, 150:] = 255    # right half: white -> top row
        scope = hud.luma_waveform(frame, out_width=256, out_height=100)
        self.assertGreater(scope[-1, 0], 0)   # left column, bottom row (0 IRE)
        self.assertEqual(scope[0, 0], 0)
        self.assertGreater(scope[0, 255], 0)  # right column, top row (100 IRE)
        self.assertEqual(scope[-1, 255], 0)

    def test_rejects_non_bgr_input(self):
        with self.assertRaises(ValueError):
            hud.luma_waveform(np.zeros((10, 10), dtype=np.uint8))

    def test_empty_frame_returns_a_blank_scope_without_crashing(self):
        scope = hud.luma_waveform(np.zeros((0, 0, 3), dtype=np.uint8), out_width=8, out_height=10)
        self.assertEqual(scope.shape, (10, 8))
        self.assertTrue(np.all(scope == 0))


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestSyntheticDemoFrame(unittest.TestCase):
    def test_default_shape_is_3x2(self):
        frame = hud.synthetic_demo_frame()
        h, w = frame.shape[:2]
        self.assertAlmostEqual(w / h, 3 / 2, places=2)

    def test_custom_size_is_honored(self):
        frame = hud.synthetic_demo_frame(width=120, height=80)
        self.assertEqual(frame.shape, (80, 120, 3))

    def test_varies_over_time_so_the_waveform_has_something_to_show(self):
        f0 = hud.synthetic_demo_frame(width=64, height=42, t=0.0)
        f1 = hud.synthetic_demo_frame(width=64, height=42, t=5.0)
        self.assertFalse(np.array_equal(f0, f1))


if __name__ == "__main__":
    unittest.main()
