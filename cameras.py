# -*- coding: utf-8 -*-
"""Camera profile loader for the Sony APS-C (BIONZ XR) toolkit.

Profiles live in cameras/<id>/profile.json. Root tools (probe_a6700.py,
experiment_a6700.py, multi_exposure.py) keep working unchanged; they may call
load_profile() to pick a body's VID/PID/handles. Original code only (MIT)."""

from __future__ import annotations

import json
import os

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cameras")
DEFAULT = "a6700"


def list_cameras():
    if not os.path.isdir(_DIR):
        return []
    return sorted(d for d in os.listdir(_DIR)
                  if os.path.isfile(os.path.join(_DIR, d, "profile.json")))


def load_profile(name: str = DEFAULT) -> dict:
    """Return the profile dict for a camera id (e.g. 'a6700', 'fx30', 'zve10m2')."""
    path = os.path.join(_DIR, name, "profile.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"no profile for '{name}'. Available: {', '.join(list_cameras())}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pid_of(name: str = DEFAULT):
    """Convenience: PC-Remote PID as int, or None if unknown."""
    p = load_profile(name)["usb"].get("pid_pc_remote")
    return int(p, 0) if isinstance(p, str) else None


if __name__ == "__main__":
    for c in list_cameras():
        p = load_profile(c)
        print(f"{c:10s} {p['model']:12s} {p['processor']:9s} "
              f"PID={p['usb']['pid_pc_remote']} [{p['status']}]")
