# Roadmap — A6700-Remote-Tools

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
- **Sony APS-C (BIONZ XR) first** — modular `cameras/` profiles: **A6700** (done),
  **FX30**, **ZV-E10 II** (same 26 MP APS-C BIONZ XR sensor).
- **BIONZ XR Full-Frame** next: e.g. A7 IV, A7C II.
- **BIONZ X** bodies afterward (older dialect): A6400, A6600, ZV-E10 Mark I.
  (ZV-E1 is Full-Frame, handled separately.)
- Community help wanted to validate per-body PIDs, property sets and control codes.

---

## 🤝 How to help

Open a [GitHub Issue](../../issues) or [Discussion](../../discussions) with your
body, firmware version and what you'd like to see (a feature, or support for your
camera). A community Discord is planned. See [`CONTRIBUTING.md`](../CONTRIBUTING.md).

*Milestones are indicative and may change as testing progresses.*
