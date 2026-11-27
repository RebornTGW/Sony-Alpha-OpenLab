#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_hud.py - Monitoring & Quick-Switch HUD for the Sony A6700 Open Gate
toolkit. Dark-mode overlay focused on framing ergonomics and instant mode
switching while shooting; does not itself touch the camera's RAM - it shells
out to the real `opengate-rs.exe` CLI (host-injector) for that, with the same
safety gates that tool already enforces.

This is a *monitoring* tool, not a new way to write to the camera: every
real-hardware action it can trigger is a plain `opengate-rs.exe` subprocess
call using that tool's own existing, already-gated flags
(`--confirm-ram-write`, etc.) - nothing here invents a new write path. There
is no software "restore to stock" command because this project is RAM-only by
design: the real revert is a cold boot / battery pull (~10 s), same as every
other write path in this repo.

Sources: `--source 0` (webcam/UVC/HDMI capture index), `--source <path>` (a
video file, or a folder of images/.ARW - same embedded-JPEG-preview handling
as `multi_exposure.py --live-ghost`), or `--demo` (a built-in synthetic 3:2
test frame, with simulated mode switching - no camera, no subprocess calls).

Keys:
  1           Stock 16:9 - returns to normal live view (no ghosting overlay)
  2           4K Open Gate 3:2 - on any failure (missing exe, non-zero exit,
              the confirm gate) the preview keeps running and the status pill
              shows "3:2 PREVIEW * CLI STANDBY" instead of crashing or
              claiming an unconfirmed RAM state
  3           Live Ghosting / Multi-Exp. - (re-)captures the CURRENT frame as
              the ghost reference instantly, no [Space]/--ghost-ref needed;
              the first capture defaults to a 50/50 "avg" blend
  H           toggle the Quick-Switch menu
  G           cycle framing guides: All -> 16:9 only -> 9:16 only -> Off
  I           toggle the status pill
  W           toggle the luma/RGB waveform
  M           (ghosting mode) cycle blend mode: dark -> bright -> avg -> add
  Space       (ghosting mode) freeze the current frame as the ghost reference
  Q           quit
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import multi_exposure as me  # reuse compose_ghost_preview / RAW_BLEND_MODES

# ---------------------------------------------------------------------------
# Pure math - crop boxes, mode cycling, command dispatch, waveform. No cv2, no
# subprocess: every function here is independently unit-testable.
# ---------------------------------------------------------------------------

GUIDE_MODES = ("all", "16:9", "9:16", "off")
MODE_STOCK = "stock"
MODE_OPEN_GATE = "open_gate"
MODE_GHOST = "ghost"
DEFAULT_PROFILE = "profile_4k_24p_stable"
SLOG3_CLIP_IRE = 94.0  # S-Log3 highlight clip point, for the waveform marker


def _center_crop(width, height, target_aspect):
    """Center crop box (x, y, w, h) fitting `target_aspect` (width/height)
    inside an arbitrary width x height source frame, cropping whichever
    dimension is in excess. A source that already matches `target_aspect`
    (e.g. the native 3:2 Open Gate sensor feed asked for a 3:2 box) yields the
    untouched full frame - cropping zero pixels is still a correct crop."""
    target_w = round(height * target_aspect)
    if target_w <= width:
        x0 = (width - target_w) // 2
        return (x0, 0, target_w, height)
    target_h = round(width / target_aspect)
    y0 = (height - target_h) // 2
    return (0, y0, width, target_h)


def crop_box_3x2(width, height):
    """Center crop fitting the 3:2 (1.5) Open Gate aspect inside an arbitrary
    source frame. On the native 3:2 sensor feed this is the untouched full
    frame; on a wider source (e.g. a 16:9 webcam/HDMI capture) it pillarboxes
    down to a narrower 3:2 window instead of silently treating the whole 16:9
    frame as if it were already 3:2 - that distinction is what makes the "3:2"
    guide visible and distinct from the outer window border on a 16:9 feed."""
    return _center_crop(width, height, 3 / 2)


def crop_box_16x9(width, height):
    """Center crop fitting 16:9 inside an arbitrary source frame - the
    cinema/YouTube safe zone. On the verified 3840x2560 Open Gate frame this
    is exactly 3840x2160 (the stock resolution), letterboxed top/bottom; on an
    already-16:9 source it's the untouched full frame."""
    return _center_crop(width, height, 16 / 9)


def crop_box_9x16(width, height):
    """Center crop fitting 9:16 inside an arbitrary source frame - the
    vertical Reels/Shorts safe zone. On the verified 3840x2560 Open Gate frame
    this is exactly 1440x2560, pillarboxed left/right."""
    return _center_crop(width, height, 9 / 16)


def cycle_guide_mode(current):
    """Advance to the next framing-guide mode: all -> 16:9 -> 9:16 -> off -> all."""
    if current not in GUIDE_MODES:
        raise ValueError(f"unknown guide mode {current!r}, want one of {GUIDE_MODES}")
    i = GUIDE_MODES.index(current)
    return GUIDE_MODES[(i + 1) % len(GUIDE_MODES)]


def cycle_blend_mode(current):
    """Advance to the next ghosting blend mode (reuses multi_exposure's 4
    RAW blend modes - same math, same names, one definition)."""
    modes = me.RAW_BLEND_MODES
    if current not in modes:
        raise ValueError(f"unknown blend mode {current!r}, want one of {modes}")
    i = modes.index(current)
    return modes[(i + 1) % len(modes)]


def format_status_pill(ram_state, profile_name, demo, cli_standby=False):
    """One-line status pill text: RAM state, active profile, source kind - or,
    when `cli_standby` is set (opengate-rs.exe missing/failed while [2] was
    pressed), the non-blocking "3:2 PREVIEW" variant instead of claiming a RAM
    state that was never actually confirmed."""
    source_label = "DEMO" if demo else "LIVE USB"
    if cli_standby:
        return f"3:2 PREVIEW • CLI STANDBY  ·  {profile_name}  ·  {source_label}"
    if ram_state not in ("STOCK 16:9", "PATCHED 3:2"):
        raise ValueError(f"unknown ram_state {ram_state!r}")
    return f"{ram_state}  ·  {profile_name}  ·  {source_label}"


def build_mode_command(exe_path, mode, demo=False, confirm=False, profile=DEFAULT_PROFILE):
    """Build the opengate-rs.exe argv for a Quick-Switch action. Pure - never
    runs anything, so it's testable without a subprocess or a real binary.

    - `--demo`: always a dry-run `--plan` (no camera, no write, regardless of
      mode or confirm).
    - Live "stock": returns None. There is no software restore in this
      RAM-only design - the real revert is a cold boot / battery pull - so
      there is nothing to execute; the caller should tell the user that
      plainly rather than running a fabricated command.
    - Live "open_gate": requires `confirm=True` (the HUD's own safety gate,
      separate from and in addition to opengate-rs.exe's own
      `--allow-unverified-usb` + interactive confirm); raises PermissionError
      otherwise rather than silently building a write command.
    """
    if mode not in (MODE_STOCK, MODE_OPEN_GATE):
        raise ValueError(f"unknown mode {mode!r}, want {MODE_STOCK!r} or {MODE_OPEN_GATE!r}")
    if demo:
        return [exe_path, profile, "--plan"]
    if mode == MODE_STOCK:
        return None
    if not confirm:
        raise PermissionError(
            "writing Open Gate to live hardware needs explicit confirm "
            "(opengate-rs.exe's own --confirm-ram-write, a real RAM write)."
        )
    return [exe_path, profile, "--confirm-ram-write"]


def ire_to_row(ire_value, out_height=100):
    """Row index (0 at top = 100 IRE, out_height-1 at bottom = 0 IRE) for a
    given IRE value, in a waveform image `out_height` rows tall."""
    ire_value = max(0.0, min(100.0, ire_value))
    row = round((1.0 - ire_value / 100.0) * (out_height - 1))
    return max(0, min(out_height - 1, row))


def luma_waveform(frame_bgr, out_width=256, out_height=100):
    """Build a luma waveform scope (0-100 IRE, bottom=0/top=100) from a BGR
    frame: each output column is a vertical histogram of one sampled source
    column's IRE values, brighter = more source pixels at that level. Pure
    numpy (BT.601 luma; no cv2 color-conversion call), so it's testable
    without OpenCV installed. Returns a (out_height, out_width) uint8 array.

    Columns are nearest-neighbor sampled, not aggregated per bucket - good
    enough for an on-screen monitoring scope, not a broadcast-grade one. A
    naive "which output bucket does this source column fall into" mapping
    leaves gaps (all-zero columns) whenever out_width > src_w; sampling
    outward from each output column instead guarantees every column maps to
    a real source column, up- or down-sampling alike.
    """
    import numpy as np

    frame_bgr = np.asarray(frame_bgr)
    if frame_bgr.ndim != 3 or frame_bgr.shape[2] < 3:
        raise ValueError("luma_waveform needs an HxWx3 (BGR) array")
    h, src_w = frame_bgr.shape[:2]
    if h == 0 or src_w == 0:
        return np.zeros((out_height, out_width), dtype=np.uint8)

    b = frame_bgr[..., 0].astype(np.float32)
    g = frame_bgr[..., 1].astype(np.float32)
    r = frame_bgr[..., 2].astype(np.float32)
    luma = 0.114 * b + 0.587 * g + 0.299 * r  # BT.601, BGR order
    ire = np.clip(luma / 255.0 * 100.0, 0.0, 100.0)

    out_cols = np.arange(out_width)
    sample_col = np.minimum(src_w - 1, (out_cols * src_w) // out_width)
    ire_sampled = ire[:, sample_col]  # (h, out_width); gather, duplicates allowed

    row_bin = np.clip((ire_sampled / 100.0 * (out_height - 1)).round().astype(np.int64), 0, out_height - 1)
    row_from_top = out_height - 1 - row_bin  # 0 IRE at the bottom row

    flat_col = np.broadcast_to(out_cols, (h, out_width)).ravel()
    flat_row = row_from_top.ravel()

    scope = np.zeros((out_height, out_width), dtype=np.float64)
    np.add.at(scope, (flat_row, flat_col), 1.0)

    col_max = scope.max(axis=0, keepdims=True)
    col_max[col_max == 0] = 1.0
    scope = scope / col_max * 255.0
    return scope.astype(np.uint8)


def synthetic_demo_frame(width=960, height=640, t=0.0):
    """A procedural 3:2 test frame for --demo: vertical color bars plus a
    slowly-moving brightness sweep, so the waveform/guides have something
    non-trivial to show without a camera. Pure numpy; cv2 only draws on top
    of it later (this function itself needs no cv2)."""
    import numpy as np

    bars_bgr = [
        (255, 255, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0),
        (255, 0, 255), (0, 0, 255), (255, 0, 0), (0, 0, 0),
    ]
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    n = len(bars_bgr)
    bar_w = max(1, width // n)
    for i, color in enumerate(bars_bgr):
        x0 = i * bar_w
        x1 = width if i == n - 1 else x0 + bar_w
        frame[:, x0:x1] = color

    # A horizontal brightness sweep that drifts with `t`, so the waveform
    # scope changes over time in --demo instead of showing one static shape.
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)
    sweep = (0.5 + 0.5 * np.sin(2 * np.pi * (xs + t * 0.05))) * 255.0
    sweep_row = sweep.astype(np.uint8)
    band_h = max(1, height // 6)
    frame[-band_h:, :, :] = sweep_row[None, :, None]
    return frame


# ---------------------------------------------------------------------------
# Rendering (cv2) - draws over a frame; not independently unit-tested beyond
# the pure math above (same split as multi_exposure.py's live_ghost).
# ---------------------------------------------------------------------------

#: Default dim amount outside the active guide box (~40% darker), and the
#: color used for each ratio's outline/ticks/label.
GUIDE_DIM_OPACITY = 0.4
GUIDE_COLORS = {"3:2": (0, 255, 0), "16:9": (0, 255, 255), "9:16": (255, 0, 255)}


def _dim_outside_box(frame, box, opacity=GUIDE_DIM_OPACITY):
    """Darken the frame outside `box` by `opacity` (0..1) - whichever bars
    that implies: top/bottom (letterbox), left/right (pillarbox), or both.
    Pure numpy, no cv2 call, so it's testable without OpenCV installed. A
    `box` that already covers the whole frame dims nothing (a no-op), which
    is exactly right for e.g. a "3:2" guide on an already-3:2 source."""
    import numpy as np

    x, y, w, h = box
    fh, fw = frame.shape[:2]
    factor = 1.0 - opacity
    bottom, right = y + h, x + w
    if y > 0:
        frame[0:y, :, :] = (frame[0:y, :, :].astype(np.float32) * factor).astype(frame.dtype)
    if bottom < fh:
        frame[bottom:fh, :, :] = (frame[bottom:fh, :, :].astype(np.float32) * factor).astype(frame.dtype)
    if x > 0:
        frame[y:bottom, 0:x, :] = (frame[y:bottom, 0:x, :].astype(np.float32) * factor).astype(frame.dtype)
    if right < fw:
        frame[y:bottom, right:fw, :] = (frame[y:bottom, right:fw, :].astype(np.float32) * factor).astype(frame.dtype)


def _draw_ratio_label(frame, box, text, color):
    """Crisp ratio label (e.g. "3:2") at the top-left corner of `box` - a dark
    outline pass then the color on top, so it reads over any background."""
    import cv2

    x, y, _w, _h = box
    pos = (x + 6, y + 20)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)


def _draw_one_guide_box(frame, box, label, color):
    import cv2

    bx, by, bw, bh = box
    cv2.rectangle(frame, (bx, by), (bx + bw - 1, by + bh - 1), color, 1)
    _draw_corner_ticks(frame, bx, by, bw, bh, color)
    _draw_ratio_label(frame, box, label, color)


def _draw_guides(frame, guide_mode):
    """Draw the active framing guide(s). Only one box gets the outside-dim
    treatment at a time (the "active" one named in `guide_mode`) so nested
    boxes in "all" mode don't compound into a muddy multi-layered dim; the
    other box outlines in "all" are still drawn, just without their own dim."""
    h, w = frame.shape[:2]
    if guide_mode == "all":
        box_3x2 = crop_box_3x2(w, h)
        _dim_outside_box(frame, box_3x2)
        _draw_one_guide_box(frame, box_3x2, "3:2", GUIDE_COLORS["3:2"])
        _draw_one_guide_box(frame, crop_box_16x9(w, h), "16:9", GUIDE_COLORS["16:9"])
        _draw_one_guide_box(frame, crop_box_9x16(w, h), "9:16", GUIDE_COLORS["9:16"])
    elif guide_mode == "16:9":
        box = crop_box_16x9(w, h)
        _dim_outside_box(frame, box)
        _draw_one_guide_box(frame, box, "16:9", GUIDE_COLORS["16:9"])
    elif guide_mode == "9:16":
        box = crop_box_9x16(w, h)
        _dim_outside_box(frame, box)
        _draw_one_guide_box(frame, box, "9:16", GUIDE_COLORS["9:16"])
    return frame


def _draw_corner_ticks(frame, bx, by, bw, bh, color, length=18, thickness=2):
    import cv2

    x1, y1 = bx, by
    x2, y2 = bx + bw - 1, by + bh - 1
    for (cx, cy, dx, dy) in (
        (x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1),
    ):
        cv2.line(frame, (cx, cy), (cx + dx * length, cy), color, thickness)
        cv2.line(frame, (cx, cy), (cx, cy + dy * length), color, thickness)


def _draw_status_pill(frame, text):
    import cv2

    h, w = frame.shape[:2]
    pad = 8
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x2, y2 = w - 12, 12 + th + pad * 2
    x1, y1 = x2 - tw - pad * 2, 12
    overlay = frame[y1:y2, x1:x2].copy()
    cv2.rectangle(frame, (x1, y1), (x2, y2), (24, 24, 24), -1)
    cv2.addWeighted(frame[y1:y2, x1:x2], 0.85, overlay, 0.15, 0, frame[y1:y2, x1:x2])
    cv2.putText(frame, text, (x1 + pad, y2 - pad - 2), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_waveform(frame, scope):
    import cv2
    import numpy as np

    sh, sw = scope.shape[:2]
    h, w = frame.shape[:2]
    x0, y1 = 12, h - 12
    y0 = y1 - sh
    x1 = x0 + sw
    if y0 < 0 or x1 > w:
        return  # frame too small for the scope at this size - skip, don't crash
    scope_bgr = cv2.cvtColor(scope, cv2.COLOR_GRAY2BGR)
    scope_bgr[:, :, 0] = 0  # green/white scope, no blue channel - classic waveform look
    region = frame[y0:y1, x0:x1]
    cv2.addWeighted(region, 0.25, scope_bgr, 0.9, 0, region)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (90, 90, 90), 1)
    clip_row = ire_to_row(SLOG3_CLIP_IRE, sh)
    cv2.line(frame, (x0, y0 + clip_row), (x1, y0 + clip_row), (0, 0, 255), 1)
    cv2.putText(frame, f"{SLOG3_CLIP_IRE:.0f} IRE", (x0 + 4, y0 + clip_row - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1, cv2.LINE_AA)


def _draw_menu(frame, visible_h_menu, active_mode):
    import cv2

    if not visible_h_menu:
        return
    pills = [
        ("1", "Stock 16:9 (3840x2160)", MODE_STOCK),
        ("2", "4K Open Gate 3:2 (3840x2560)", MODE_OPEN_GATE),
        ("3", "Live Ghosting / Multi-Exp.", MODE_GHOST),
    ]
    pad = 8
    line_h = 26
    font, scale, thickness = cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
    texts = [f"[{key}] {label}" for key, label, _ in pills]
    max_w = max(cv2.getTextSize(t, font, scale, thickness)[0][0] for t in texts)

    h, w = frame.shape[:2]
    x1, y1 = 12, 12
    x2 = min(w, x1 + max_w + pad * 2)
    y2 = min(h, y1 + len(pills) * line_h + pad)

    # Same dark semi-transparent backing as the status pill, so the menu text
    # stays crisp over bright/white backgrounds (e.g. the --demo color bars)
    # instead of just floating unreadably on top of them.
    overlay = frame[y1:y2, x1:x2].copy()
    cv2.rectangle(frame, (x1, y1), (x2, y2), (24, 24, 24), -1)
    cv2.addWeighted(frame[y1:y2, x1:x2], 0.85, overlay, 0.15, 0, frame[y1:y2, x1:x2])

    y = y1
    for key, label, mode in pills:
        text = f"[{key}] {label}"
        color = (0, 255, 0) if mode == active_mode else (220, 220, 220)
        cv2.putText(frame, text, (x1 + pad, y + 18), font, scale, color, thickness, cv2.LINE_AA)
        y += line_h


# ---------------------------------------------------------------------------
# Main interactive loop
# ---------------------------------------------------------------------------

def run_mode_command(exe_path, mode, demo=False, confirm=False, profile=DEFAULT_PROFILE):
    """Dispatch one Quick-Switch action. Never raises - every failure mode
    (missing/unrunnable exe, a non-zero exit code, the HUD's own confirm
    refusal, an unknown mode) is caught and reported, returning False instead,
    so a bad command can never crash the preview loop. Returns True only when
    the dispatch actually succeeded; a live "stock" request - no software
    restore exists for this RAM-only design - counts as its own successful,
    expected outcome, not a failure.
    """
    try:
        cmd = build_mode_command(exe_path, mode, demo=demo, confirm=confirm, profile=profile)
    except (PermissionError, ValueError) as e:
        print(f"[monitor-hud] {e}")
        return False
    if cmd is None:
        print("[monitor-hud] no software restore to stock - this project is "
              "RAM-only; revert with a cold boot / battery pull (~10s).")
        return True
    import subprocess
    print(f"[monitor-hud] running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=False)
    except OSError as e:
        print(f"[monitor-hud] could not run {exe_path!r}: {e}")
        return False
    if result.returncode != 0:
        print(f"[monitor-hud] {exe_path} exited with code {result.returncode}")
        return False
    return True


def _open_source(source, demo):
    """Return (capture, image_paths, rawpy_module) following the same shape
    multi_exposure.live_ghost() uses, so --source behaves the same way for
    webcam index / video file / image-or-.ARW folder. --demo bypasses all of
    this (handled by the caller)."""
    import cv2

    source_path = os.fspath(source)
    if os.path.isdir(source_path):
        supported = {".arw", ".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
        image_paths = sorted(
            os.path.join(source_path, name)
            for name in os.listdir(source_path)
            if os.path.splitext(name)[1].lower() in supported
        )
        rawpy_module = None
        if any(os.path.splitext(p)[1].lower() == ".arw" for p in image_paths):
            try:
                import rawpy as rawpy_module
            except ImportError:
                print("[monitor-hud] rawpy is missing; skipping .ARW previews "
                      "(install with: pip install rawpy).")
                image_paths = [p for p in image_paths if os.path.splitext(p)[1].lower() != ".arw"]
        if not image_paths:
            raise RuntimeError(f"no supported images found in {source_path}")
        return None, image_paths, rawpy_module

    source_value = int(source_path) if source_path.isdecimal() else source_path
    capture = cv2.VideoCapture(source_value)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"could not open source {source_path!r}")
    return capture, None, None


def _read_frame(capture, image_paths, image_index, rawpy_module):
    import cv2

    if image_paths is not None:
        path = image_paths[image_index[0]]
        image_index[0] = (image_index[0] + 1) % len(image_paths)
        if os.path.splitext(path)[1].lower() == ".arw":
            import numpy as np
            with rawpy_module.imread(path) as raw:
                thumb = raw.extract_thumb()
            if thumb.format != rawpy_module.ThumbFormat.JPEG:
                raise RuntimeError(f"{path} has no JPEG preview")
            encoded = np.frombuffer(thumb.data, dtype=np.uint8)
            return cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        return cv2.imread(path)

    ok, frame = capture.read()
    if not ok:
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = capture.read()
    if not ok:
        raise RuntimeError("failed to read a frame from the source")
    return frame


def initial_hud_state():
    """The HUD's starting state - see `handle_key()`."""
    return {
        "menu_visible": True,
        "guide_mode": "all",
        "status_visible": True,
        "waveform_visible": False,
        "active_mode": MODE_OPEN_GATE,
        "ram_state": "STOCK 16:9",
        "blend_mode": "avg",
        "ghost_ref": None,
        "cli_standby": False,
    }


def handle_key(key, state, frame, demo=False, exe_path="opengate-rs.exe", profile=DEFAULT_PROFILE):
    """Apply one keypress to the HUD state, returning the new state (a
    shallow copy - `state` itself is not mutated). `frame` is the current live
    frame (needed by Space/[3]'s instant capture). Pure aside from the
    isolated, itself-never-raising `run_mode_command()` subprocess dispatch
    for [1]/[2] - no cv2 drawing happens here, so this is testable without a
    window, a camera, or a real opengate-rs.exe.

    [2] (open_gate): on success, the normal "PATCHED 3:2" status is shown; on
    *any* failure (missing exe, non-zero exit, the confirm gate), `cli_standby`
    is set instead so the status pill shows "3:2 PREVIEW" rather than claiming
    an unconfirmed RAM state, the preview loop is left running either way, and
    - if framing guides were off - they're switched on so the 3:2 framing is
    at least visible while in standby.

    [3] (ghost): always (re-)captures `frame` as the ghost reference, so
    ghosting works immediately on live video without a prior [Space] or a
    `--ghost-ref` CLI option. The very first capture (no reference existed
    yet) also resets the blend mode to "avg" - a plain 50/50 blend - so the
    default ghosting view is the one described as "semi-transparent 50%";
    refreshing an already-active reference does not touch a since-cycled
    blend mode.
    """
    state = dict(state)
    if key in (ord("h"), ord("H")):
        state["menu_visible"] = not state["menu_visible"]
    elif key in (ord("g"), ord("G")):
        state["guide_mode"] = cycle_guide_mode(state["guide_mode"])
    elif key in (ord("i"), ord("I")):
        state["status_visible"] = not state["status_visible"]
    elif key in (ord("w"), ord("W")):
        state["waveform_visible"] = not state["waveform_visible"]
    elif key in (ord("m"), ord("M")):
        state["blend_mode"] = cycle_blend_mode(state["blend_mode"])
    elif key == ord(" "):
        state["ghost_ref"] = frame.copy()
    elif key == ord("1"):
        state["active_mode"] = MODE_STOCK
        state["ram_state"] = "STOCK 16:9"
        state["cli_standby"] = False
        run_mode_command(exe_path, MODE_STOCK, demo=demo, confirm=False, profile=profile)
    elif key == ord("2"):
        state["active_mode"] = MODE_OPEN_GATE
        ok = run_mode_command(exe_path, MODE_OPEN_GATE, demo=demo, confirm=demo, profile=profile)
        if ok:
            state["ram_state"] = "PATCHED 3:2"
            state["cli_standby"] = False
        else:
            state["cli_standby"] = True
            if state["guide_mode"] == "off":
                state["guide_mode"] = "all"
    elif key == ord("3"):
        if state["ghost_ref"] is None:
            state["blend_mode"] = "avg"
        state["ghost_ref"] = frame.copy()
        state["active_mode"] = MODE_GHOST
    return state


def monitor_hud(source, demo=False, exe_path="opengate-rs.exe", profile=DEFAULT_PROFILE):
    """Run the Monitoring & Quick-Switch HUD. Returns True on a clean exit."""
    try:
        import cv2
    except ImportError:
        print("[monitor-hud] OpenCV is required; install it with: pip install opencv-python")
        return False

    capture = None
    image_paths = None
    rawpy_module = None
    if not demo:
        try:
            capture, image_paths, rawpy_module = _open_source(source, demo)
        except RuntimeError as e:
            print(f"[monitor-hud] {e}")
            return False
    image_index = [0]

    state = initial_hud_state()
    t = 0.0

    try:
        while True:
            if demo:
                frame = synthetic_demo_frame(t=t)
                t += 1.0
            else:
                frame = _read_frame(capture, image_paths, image_index, rawpy_module)
            if frame is None:
                print("[monitor-hud] could not decode a frame from the source")
                return False

            display = frame.copy()
            if state["active_mode"] == MODE_GHOST and state["ghost_ref"] is not None:
                ref = state["ghost_ref"]
                if ref.shape != display.shape:
                    ref = cv2.resize(ref, (display.shape[1], display.shape[0]))
                display = me.compose_ghost_preview(display, [ref], state["blend_mode"])

            if state["guide_mode"] != "off":
                _draw_guides(display, state["guide_mode"])
            if state["status_visible"]:
                pill = format_status_pill(state["ram_state"], profile, demo, cli_standby=state["cli_standby"])
                _draw_status_pill(display, pill)
            if state["waveform_visible"]:
                scope = luma_waveform(display)
                _draw_waveform(display, scope)
            _draw_menu(display, state["menu_visible"], state["active_mode"])

            cv2.imshow("Monitor HUD", display)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), ord("Q")):
                break
            state = handle_key(key, state, frame, demo=demo, exe_path=exe_path, profile=profile)
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()
    return True


def main():
    ap = argparse.ArgumentParser(
        description="Monitoring & Quick-Switch HUD for the A6700 Open Gate toolkit."
    )
    ap.add_argument("--source", default=None, metavar="INDEX|PATH",
                     help="Webcam index (e.g. 0), video file, or image/.ARW folder.")
    ap.add_argument("--demo", action="store_true",
                     help="Synthetic 3:2 test frame, simulated mode switching - no camera.")
    ap.add_argument("--exe", default="opengate-rs.exe", metavar="PATH",
                     help="Path to the opengate-rs.exe CLI (default: opengate-rs.exe on PATH).")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, metavar="NAME",
                     help=f"Open Gate profile for [2] (default: {DEFAULT_PROFILE}).")
    args = ap.parse_args()

    if not args.demo and args.source is None:
        ap.error("--source is required unless --demo is given")

    ok = monitor_hud(args.source, demo=args.demo, exe_path=args.exe, profile=args.profile)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
