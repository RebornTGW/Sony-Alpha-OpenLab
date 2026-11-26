# Camera profiles — Sony APS-C (BIONZ XR)

Per-body profiles (`<id>/profile.json`) for the toolkit. Load from root tools:

```python
from cameras import load_profile, pid_of
p = load_profile("a6700")   # or "fx30", "zve10m2"
```

List: `python cameras.py`

| Id | Model | Sensor / chip | Status |
|---|---|---|---|
| `a6700` | ILCE-6700 | 26 MP APS-C / BIONZ XR | ✅ verified live (fw 2.00) |
| `fx30` | ILME-FX30 | 26 MP APS-C / BIONZ XR | planned (same sensor+chip) |
| `zve10m2` | ZV-E10 II | 26 MP APS-C / BIONZ XR | placeholder |

Older **BIONZ X** bodies (A6400, A6600, ZV-E10 Mark I) come later — different
protocol generation. **ZV-E1 is Full-Frame** (not here). Profiles are original
data (MIT); no firmware or third-party (GPL) content.
