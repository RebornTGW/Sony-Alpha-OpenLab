# Contributing — Sony-Alpha-OpenLab

**🌍 Language: English · [Français](CONTRIBUTING.fr.md)**

Thanks for your interest! This project documents and tests the Sony A6700
remote-control protocol for **interoperability and study**. Its scope is **strictly
limited to two goals — Open Gate 3:2 and multi-exposure — with no permanent
modification of the camera.** A few simple rules keep it clean, safe, and publicly
shareable.

## 🔒 Rule #1 — No firmware content

**Never commit** any file extracted from the Sony firmware or any proprietary binary
data, in particular:

- firmware and libraries: `*.so`, `*.bin`, `*.DAT`, `*.ko`, `*.elf`, `*.img`;
- decompressed firmware, dumps, partition images, `.rodata`/`.data` excerpts;
- any copy of disassembled code reproducing Sony code.

The `.gitignore` already blocks these extensions, but vigilance is on you. What is
allowed: **protocol constants** (opcodes, property codes, symbolic names) and
**documentation** describing the protocol — these are interoperability facts, not
redistributed code.

## 🛡️ Rule #2 — Read-only first

The reference tool (`probe_a6700.py`) is **strictly read-only** and stays that way by
default. Any contribution introducing a write or control operation
(`SetExtDevicePropValue` 0x9205, `ControlDevice` 0x9207, `SendObject`, formatting,
firmware update…) must:

1. be **disabled by default** and guarded by an explicit flag (e.g. `--enable-write`)
   with confirmation;
2. never be added to the `READ_ONLY_OPS` whitelist;
3. clearly document its physical effect on the camera;
4. stay **within scope** (Open Gate 3:2 / multi-exposure) and never cause any
   **permanent modification** of settings or firmware.

Reminder: S1/S2/Movie Rec and any `ControlDevice` action change the camera's
physical state (shutter, recording). Handle them with care.

## 🧪 Rule #3 — Responsible testing

- Test on **your own hardware**, battery charged, without a card holding important
  data.
- Prefer `--no-sdio` for a first contact.
- In your PR, report the model, firmware version, and OS used.

## 🔧 Environment setup

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, install the WinUSB driver on the camera's PTP interface via Zadig
(see [README.md](README.md)).

## 📐 Code style

- Python 3.9+, **PEP 8** compliant; line width ~100 columns.
- Explicit names; docstrings and comments **in English** (the code language).
- Protocol constants (opcodes, codes) are grouped and named.
- Avoid unnecessary dependencies: the core must only depend on `pyusb`.

## 🔀 PR process

1. Fork and create a branch: `git checkout -b feat/my-feature`.
2. One commit = one intent. Imperative messages (e.g. `add GetExtDeviceInfo parser`).
3. Verify: `python -c "import ast; ast.parse(open('probe_a6700.py').read())"`
   and, if possible, a real read-only test.
4. Confirm **no binary** was added: `git status` + `git ls-files`.
5. Open the PR describing the behavior and any impact on the camera.

## 📄 License

By contributing, you agree that your contribution is distributed under the **MIT**
license (see [LICENSE](LICENSE)).
