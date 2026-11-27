# Roadmap — Sony-Open-Gate-Lab

**🌍 Language: English · [Français](ROADMAP.md)**

An open-source toolkit for Sony Alpha cameras, developed and tested first on the
**Sony A6700**. This page tracks what works and where the project is going. It
describes **capabilities and goals only** — no proprietary firmware internals.

> Scope reminder: research is limited to **Open Gate 3:2** and **multi-exposure**,
> with **no permanent modification** of the camera. Read-only by default; any write
> is opt-in and session-only (erased on reboot / battery removal).

---

## ✅ Done

- **USB PTP / "SDIO" probe** (`probe_a6700.py`) — strictly read-only: open a
  session, read device info, enumerate exposed properties and control codes, decode
  current values and allowed values. Validated live on the A6700 (firmware 2.00).
- **Shooting control** (`experiment_a6700.py`) — session-only: half-press (AF),
  full-press (shutter) and movie start/stop over USB, all confirmed working.
- **Automated multi-exposure** (`multi_exposure.py`) — capture N frames at a
  controlled interval, with optional read-only image download and local stacking
  (average, lighten, screen).
- **Native double-exposure experience** — step-by-step interactive mode and a
  real-time Live View overlay window (align frame 2 over frame 1, Space to capture,
  instant blend), reproducing the Fujifilm/Canon in-camera flow.
- **Reference documentation** — protocol overview, a dictionary of device-property
  and control codes, and an experimental results page, all bilingual (EN/FR).
- **Safety model** — a read-only-by-default design with an explicit opt-in gate for
  any session-only write, and a strict ban on shipping firmware content.

---

## 🔭 Next steps

### 1. Portability (mobile / embedded)
- Package the toolkit to run beyond a desktop: a small embedded host (e.g.
  single-board computer) and, longer term, a mobile companion.
- Keep a clean transport/UI separation so the same core drives CLI, embedded and
  mobile front-ends.

### 2. Open Gate 3:2 — volatile-memory (RAM-only) study
- Our live tests show the 3:2 video switch is blocked above the USB protocol, at the
  application layer. A plain property write is accepted but ignored.
- Next: study a **volatile, session-only memory channel** (nothing written to
  persistent storage or firmware; changes gone on reboot) to understand where that
  gate is enforced, strictly as research.
- This remains exploratory and is pursued only within the no-permanent-write policy.

### 3. More Sony Alpha bodies
- **BIONZ XR first** — 14 bodies now catalogued under `cameras/`, grouped by
  sensor family: **A6700** (verified), plus 13 locked-skeleton bodies (FX30,
  ZV-E10 II, A7S III, FX3, ZV-E1, A7 IV, A7C II, FX2, A7R V, A7CR, A1, A1 II,
  A9 III) awaiting hardware (`--dump-ram` / `--scan-dump`).
- **BIONZ X** bodies are a different, older protocol generation -
  `host-injector`'s Senser `0x0336` path now refuses them outright (see
  `host-injector/src/camera.rs`'s PID blocklist) rather than risk sending that
  protocol at incompatible hardware.
- Community help wanted to validate per-body PIDs, property sets and control codes.

### 4. Upcoming BIONZ X research (Sony A6400)
- A separate research track, not an extension of `host-injector`'s Senser
  `0x0336` path (explicitly blocked there - see §3 above and the root
  README's "Security Architecture & BIONZ X Guardrails" table).
- **RAW 16-bit multi-exposure validation**: confirm `multi_exposure.py`'s
  `--raw-blend` (linear 16-bit `.ARW` stacking) and `monitor_hud.py` behave
  correctly on BIONZ X's sensor/RAW output - both already work on any Sony
  body generically, this is about validating assumptions, not new code.
- **Non-Senser USB/PMCA protocol study**: BIONZ X bodies use their own,
  undocumented-here service-mode dialect. Read-only study first, same
  clean-room rules as everything else in this repo - no write path until (if
  ever) a BIONZ X-specific protocol is independently verified safe.

---

## 🤝 How to help

Open a [GitHub Issue](../../issues) or [Discussion](../../discussions) with your
body, firmware version and what you'd like to see (a feature, or support for your
camera). A community Discord is planned. See [`CONTRIBUTING.md`](../CONTRIBUTING.md).

*Milestones are indicative and may change as testing progresses.*
