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
from unittest import mock

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
    def test_guide_mode_cycles_in_order_and_wraps(self):
        seq = [hud.GUIDE_MODES[0]]
        for _ in range(len(hud.GUIDE_MODES)):
            seq.append(hud.cycle_guide_mode(seq[-1]))
        self.assertEqual(seq, ["main", "main+9:16", "off", "main"])

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


class TestCropBoxesOnA16x9Source(unittest.TestCase):
    """Regression: on a 16:9 source (e.g. a 720p/1080p webcam), the 3:2 guide
    used to just be "the whole frame" - identical to the 16:9 window border,
    so it was never visually distinct. crop_box_3x2() now computes a real
    pillarboxed 3:2 crop on a wider-than-3:2 source instead."""

    def test_3x2_pillarboxes_on_a_1920x1080_source(self):
        x, y, w, h = hud.crop_box_3x2(1920, 1080)
        self.assertEqual((w, h), (1620, 1080))  # 1080 * 3/2 = 1620
        self.assertEqual(y, 0)  # full height kept
        self.assertEqual(x, (1920 - 1620) // 2)
        self.assertLess(w, 1920, "3:2 box must be narrower than the 16:9 frame")

    def test_3x2_pillarboxes_on_a_1280x720_source(self):
        x, y, w, h = hud.crop_box_3x2(1280, 720)
        self.assertEqual((w, h), (1080, 720))  # 720 * 3/2 = 1080
        self.assertEqual(y, 0)
        self.assertEqual(x, (1280 - 1080) // 2)

    def test_16x9_is_the_untouched_full_frame_on_a_16x9_source(self):
        # The 16:9 guide on an already-16:9 source should NOT crop anything.
        self.assertEqual(hud.crop_box_16x9(1920, 1080), (0, 0, 1920, 1080))

    def test_9x16_still_pillarboxes_on_a_16x9_source(self):
        x, y, w, h = hud.crop_box_9x16(1920, 1080)
        self.assertEqual(y, 0)
        self.assertLess(w, 1920)


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestDimOutsideBox(unittest.TestCase):
    """_dim_outside_box() is the "3:2 dim overlay rendering" the OSD guides
    use - pure numpy, no cv2, so it's testable without OpenCV installed."""

    def test_dims_letterbox_bars_top_and_bottom_only(self):
        frame = np.full((100, 100, 3), 200, dtype=np.uint8)
        box = (0, 20, 100, 60)  # full width, vertical letterbox
        hud._dim_outside_box(frame, box, opacity=0.4)
        self.assertTrue(np.all(frame[0:20] == round(200 * 0.6)))   # top bar dimmed
        self.assertTrue(np.all(frame[80:100] == round(200 * 0.6)))  # bottom bar dimmed
        self.assertTrue(np.all(frame[20:80] == 200))  # inside the box, untouched

    def test_dims_pillarbox_bars_left_and_right_only(self):
        frame = np.full((100, 100, 3), 200, dtype=np.uint8)
        box = (20, 0, 60, 100)  # full height, horizontal pillarbox
        hud._dim_outside_box(frame, box, opacity=0.4)
        self.assertTrue(np.all(frame[:, 0:20] == round(200 * 0.6)))
        self.assertTrue(np.all(frame[:, 80:100] == round(200 * 0.6)))
        self.assertTrue(np.all(frame[:, 20:80] == 200))

    def test_full_frame_box_dims_nothing(self):
        # e.g. a "3:2" guide on an already-3:2 source: the box IS the frame.
        frame = np.full((50, 50, 3), 128, dtype=np.uint8)
        hud._dim_outside_box(frame, (0, 0, 50, 50), opacity=0.4)
        self.assertTrue(np.all(frame == 128))

    def test_opacity_controls_dim_strength(self):
        frame = np.full((10, 10, 3), 255, dtype=np.uint8)
        hud._dim_outside_box(frame, (0, 2, 10, 6), opacity=0.5)
        self.assertTrue(np.all(frame[0:2] == 127))  # round(255 * 0.5)


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestRunModeCommand(unittest.TestCase):
    """run_mode_command() must never raise - it's the dispatcher behind [1]/[2]
    in the live preview loop, and a raised exception there used to crash the
    whole OpenCV window (reproduced before this fix: pressing [2] live without
    a prior confirm raised PermissionError straight out of the old
    _run_mode_command(), killing monitor_hud())."""

    def test_demo_success_returns_true(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            ok = hud.run_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=True)
        self.assertTrue(ok)
        run.assert_called_once()

    def test_live_stock_returns_true_without_running_anything(self):
        with mock.patch("subprocess.run") as run:
            ok = hud.run_mode_command("opengate-rs.exe", hud.MODE_STOCK, demo=False)
        self.assertTrue(ok)
        run.assert_not_called()

    def test_live_open_gate_without_confirm_returns_false_not_an_exception(self):
        with mock.patch("subprocess.run") as run:
            ok = hud.run_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=False, confirm=False)
        self.assertFalse(ok)
        run.assert_not_called()

    def test_missing_exe_returns_false_not_an_exception(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            ok = hud.run_mode_command("nonexistent.exe", hud.MODE_OPEN_GATE, demo=False, confirm=True)
        self.assertFalse(ok)

    def test_nonzero_exit_code_returns_false(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            ok = hud.run_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=False, confirm=True)
        self.assertFalse(ok)

    def test_successful_live_dispatch_returns_true(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)) as run:
            ok = hud.run_mode_command("opengate-rs.exe", hud.MODE_OPEN_GATE, demo=False, confirm=True)
        self.assertTrue(ok)
        run.assert_called_once_with(
            ["opengate-rs.exe", hud.DEFAULT_PROFILE, "--confirm-ram-write"], check=False)

    def test_unknown_mode_returns_false(self):
        with mock.patch("subprocess.run") as run:
            ok = hud.run_mode_command("opengate-rs.exe", "bogus-mode")
        self.assertFalse(ok)
        run.assert_not_called()


class TestStatusPillCliStandby(unittest.TestCase):
    def test_cli_standby_overrides_ram_state_text(self):
        text = hud.format_status_pill("PATCHED 3:2", "profile_4k_24p_stable", False, cli_standby=True)
        self.assertIn("3:2 PREVIEW", text)
        self.assertIn("CLI STANDBY", text)
        self.assertNotIn("PATCHED 3:2", text)

    def test_cli_standby_still_reports_profile_and_source(self):
        text = hud.format_status_pill("STOCK 16:9", "fx30_v5.00", True, cli_standby=True)
        self.assertIn("fx30_v5.00", text)
        self.assertIn("DEMO", text)

    def test_default_is_not_standby(self):
        text = hud.format_status_pill("STOCK 16:9", "p", False)
        self.assertNotIn("STANDBY", text)


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestHandleKey(unittest.TestCase):
    """handle_key() is the pure state-transition function behind every
    keypress in the preview loop - testable without a window, a camera, or a
    real opengate-rs.exe."""

    def setUp(self):
        self.frame = np.full((4, 4, 3), 77, dtype=np.uint8)

    def test_key_2_success_patches_and_clears_standby(self):
        state = hud.initial_hud_state()
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
            state = hud.handle_key(ord("2"), state, self.frame, demo=True)
        self.assertEqual(state["active_mode"], hud.MODE_OPEN_GATE)
        self.assertEqual(state["ram_state"], "PATCHED 3:2")
        self.assertFalse(state["cli_standby"])

    def test_key_2_failure_never_raises_and_sets_standby_instead_of_crashing(self):
        state = hud.initial_hud_state()
        state["ram_state"] = "STOCK 16:9"
        # Live mode, no confirm mechanism wired yet -> build_mode_command()
        # raises PermissionError internally; handle_key() must absorb it.
        try:
            with mock.patch("subprocess.run") as run:
                state = hud.handle_key(ord("2"), state, self.frame, demo=False)
        except Exception as e:  # pragma: no cover - this is exactly the bug
            self.fail(f"handle_key([2]) must never raise, raised {type(e).__name__}: {e}")
        run.assert_not_called()
        self.assertTrue(state["cli_standby"])
        self.assertEqual(state["ram_state"], "STOCK 16:9")  # not overwritten to PATCHED

    def test_key_2_failure_turns_guides_on_if_they_were_off(self):
        state = hud.initial_hud_state()
        state["guide_mode"] = "off"
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            state = hud.handle_key(ord("2"), state, self.frame, demo=False)
        self.assertEqual(state["guide_mode"], "main+9:16")

    def test_key_2_failure_leaves_existing_guide_mode_alone(self):
        state = hud.initial_hud_state()
        state["guide_mode"] = "16:9"
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            state = hud.handle_key(ord("2"), state, self.frame, demo=False)
        self.assertEqual(state["guide_mode"], "16:9")

    def test_key_3_first_press_captures_frame_and_defaults_to_avg_blend(self):
        state = hud.initial_hud_state()
        state["blend_mode"] = "bright"  # should be reset on the FIRST capture
        state = hud.handle_key(ord("3"), state, self.frame)
        self.assertEqual(state["active_mode"], hud.MODE_GHOST)
        self.assertEqual(state["blend_mode"], "avg")
        self.assertTrue(np.array_equal(state["ghost_ref"], self.frame))

    def test_key_3_second_press_refreshes_reference_without_resetting_blend_mode(self):
        state = hud.initial_hud_state()
        state = hud.handle_key(ord("3"), state, self.frame)  # first capture -> avg
        state["blend_mode"] = "bright"  # user cycled it with M in the meantime
        new_frame = np.full((4, 4, 3), 200, dtype=np.uint8)
        state = hud.handle_key(ord("3"), state, new_frame)
        self.assertEqual(state["blend_mode"], "bright")  # untouched this time
        self.assertTrue(np.array_equal(state["ghost_ref"], new_frame))  # refreshed

    def test_key_3_capture_is_a_copy_not_a_reference(self):
        state = hud.initial_hud_state()
        state = hud.handle_key(ord("3"), state, self.frame)
        self.frame[:] = 0
        self.assertTrue(np.all(state["ghost_ref"] == 77), "must be a copy, not aliased")

    def test_key_1_returns_to_normal_live_view_and_clears_standby(self):
        state = hud.initial_hud_state()
        state["active_mode"] = hud.MODE_GHOST
        state["cli_standby"] = True
        with mock.patch("subprocess.run"):
            state = hud.handle_key(ord("1"), state, self.frame, demo=False)
        self.assertEqual(state["active_mode"], hud.MODE_STOCK)
        self.assertEqual(state["ram_state"], "STOCK 16:9")
        self.assertFalse(state["cli_standby"])

    def test_unrecognized_key_leaves_state_unchanged(self):
        state = hud.initial_hud_state()
        new_state = hud.handle_key(ord("z"), state, self.frame)
        self.assertEqual(new_state, state)

    def test_state_is_not_mutated_in_place(self):
        state = hud.initial_hud_state()
        original = dict(state)
        hud.handle_key(ord("g"), state, self.frame)
        self.assertEqual(state, original)


class TestPrimaryAspectForMode(unittest.TestCase):
    def test_stock_is_16x9(self):
        self.assertEqual(hud._primary_aspect_for_mode(hud.MODE_STOCK), "16:9")

    def test_open_gate_is_3x2(self):
        self.assertEqual(hud._primary_aspect_for_mode(hud.MODE_OPEN_GATE), "3:2")

    def test_ghost_is_3x2(self):
        self.assertEqual(hud._primary_aspect_for_mode(hud.MODE_GHOST), "3:2")


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestDrawGuidesActiveAspectOnly(unittest.TestCase):
    """_draw_guides() now shows only the single aspect the active mode frames
    for (16:9 for Stock, 3:2 for Open Gate/ghosting) - never both at once, so
    the two boxes can't visually collide. Tested by mocking _draw_one_guide_box
    to see exactly which box(es) get drawn, rather than inspecting rendered
    pixels (which would collide with legitimate border/tick/label drawing)."""

    def test_stock_mode_draws_only_16x9(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with mock.patch.object(hud, "_draw_one_guide_box") as draw_box:
            hud._draw_guides(frame, "main", hud.MODE_STOCK)
        draw_box.assert_called_once()
        self.assertEqual(draw_box.call_args[0][2], "16:9")

    def test_open_gate_mode_draws_only_3x2(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with mock.patch.object(hud, "_draw_one_guide_box") as draw_box:
            hud._draw_guides(frame, "main", hud.MODE_OPEN_GATE)
        draw_box.assert_called_once()
        self.assertEqual(draw_box.call_args[0][2], "3:2")

    def test_ghost_mode_draws_only_3x2(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with mock.patch.object(hud, "_draw_one_guide_box") as draw_box:
            hud._draw_guides(frame, "main", hud.MODE_GHOST)
        self.assertEqual(draw_box.call_args[0][2], "3:2")

    def test_main_plus_9x16_adds_a_second_call_for_9x16(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with mock.patch.object(hud, "_draw_one_guide_box") as draw_box:
            hud._draw_guides(frame, "main+9:16", hud.MODE_OPEN_GATE)
        self.assertEqual(draw_box.call_count, 2)
        labels = [c[0][2] for c in draw_box.call_args_list]
        self.assertEqual(labels, ["3:2", "9:16"])

    def test_off_draws_nothing(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with mock.patch.object(hud, "_draw_one_guide_box") as draw_box:
            hud._draw_guides(frame, "off", hud.MODE_OPEN_GATE)
        draw_box.assert_not_called()


@unittest.skipUnless(HAVE_NUMPY, "numpy required")
class TestRatioLabelPosition(unittest.TestCase):
    """The ratio label moved to the bottom-left of the crop box (top-left
    collided with the Quick-Switch menu panel)."""

    def test_label_position_is_near_the_bottom_left_of_the_box(self):
        box = (10, 20, 100, 200)  # x, y, w, h -> bottom edge at y+h=220
        with mock.patch("cv2.putText") as put_text:
            hud._draw_ratio_label(np.zeros((300, 300, 3), dtype=np.uint8), box, "3:2", (0, 255, 0))
        self.assertEqual(put_text.call_count, 2)
        pos = put_text.call_args_list[0][0][2]  # positional arg index 2 = pos
        x, y, w, h = box
        self.assertEqual(pos[0], x + 6)
        self.assertGreater(pos[1], y + h // 2)  # clearly in the lower half of the box
        self.assertLess(pos[1], y + h)  # still inside the box, not below it


if __name__ == "__main__":
    unittest.main()
