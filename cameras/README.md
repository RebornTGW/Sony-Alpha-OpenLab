# Camera profiles — Sony BIONZ XR

Per-body profiles (`<id>/profile.json`) for the toolkit. Load from root tools:

```python
from cameras import load_profile, pid_of
p = load_profile("a6700")   # or any id below
```

List: `python cameras.py`

All 14 bodies share the **BIONZ XR** processor; they are grouped below by sensor
family, since that is what mostly determines how close a body's Open Gate memory
layout is expected to be to the verified A6700 reference.

### APS-C 26 MP (IMX571)

| Id | Model | Status |
|---|---|---|
| `a6700` | ILCE-6700 | ✅ verified live (fw 2.00) — reference body |
| `fx30` | ILME-FX30 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `zve10m2` | ILCZE-10M2 | awaiting hardware (`--dump-ram` / `--scan-dump`) |

### Full-Frame 12.1 MP

| Id | Model | Status |
|---|---|---|
| `a7siii` | ILCE-7SM3 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `fx3` | ILME-FX3 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `zve1` | ILCE-ZVE1 (unconfirmed) | awaiting hardware (`--dump-ram` / `--scan-dump`) |

### Full-Frame 33 MP

| Id | Model | Status |
|---|---|---|
| `a7m4` | ILCE-7M4 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `a7c2` | ILCE-7CM2 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `fx2` | ILME-FX2 (unconfirmed) | awaiting hardware (`--dump-ram` / `--scan-dump`) |

### Full-Frame 61 MP

| Id | Model | Status |
|---|---|---|
| `a7r5` | ILCE-7RM5 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `a7cr` | ILCE-7CR | awaiting hardware (`--dump-ram` / `--scan-dump`) |

### Full-Frame Stacked / Global Shutter

| Id | Model | Status |
|---|---|---|
| `a1` | ILCE-1 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `a1ii` | ILCE-1M2 | awaiting hardware (`--dump-ram` / `--scan-dump`) |
| `a9iii` | ILCE-9M3 | awaiting hardware (`--dump-ram` / `--scan-dump`) |

Older **BIONZ X** bodies (A6400, A6600, ZV-E10 Mark I) are a different protocol
generation and are not catalogued here yet.

Every non-A6700 entry is a **placeholder**: model/sensor are public spec-sheet
facts, but USB PID and exact model code are `null`/marked unconfirmed until
checked on real hardware, and none of them carry any Open Gate memory offsets -
see [`../profiles/`](../profiles/) and
["Contributing a New BIONZ XR Body"](../README.md#-contributing-a-new-bionz-xr-body)
in the root README for how those get populated, read-only and clean-room, once a
body is in hand. Profiles here are original data (MIT); no firmware or
third-party (GPL) content.
