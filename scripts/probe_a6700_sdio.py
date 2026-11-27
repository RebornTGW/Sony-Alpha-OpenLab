#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/probe_a6700_sdio.py - CLI entrypoint for `sdio_probe.py`.

Thin wrapper so the probe can be run as `python scripts/probe_a6700_sdio.py`
from the repo root without needing the project installed as a package. See
`sdio_probe.py` for the implementation and `docs/BIONZ_XR_PTP_SDIO.md` for
the protocol background.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sdio_probe import main  # noqa: E402

if __name__ == "__main__":
    main()
