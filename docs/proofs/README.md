# Proofs — anonymized evidence

Curated, **anonymized** extracts of our A6700 (firmware 2.00) hardware tests, plus a
home for proof screenshots. Nothing here contains a USB serial number, a local
`C:\Users\...` path, or any block of Sony firmware bytes — only high-level diagnostic
summary lines (verdicts, panel types, span counts, window geometry) and resolution
dimensions.

Raw dumps (`camera_private/`, `*_dump/`, `readcheck_result.txt`, `transcript.jsonl`)
are **git-ignored** and never published: they carry firmware-derived content.

## Contents

| File | What it shows |
|---|---|
| `stable_M19_summary.txt` | the stable run: 3840×2560 recorded clean with the M19 encoder |
| `crash_L19_summary.txt` | the L19 encoder rebooting the kernel on the MOVIE switch |

## Screenshots (to add)

Drop proof captures here (PNG/JPG). Suggested, all with the serial blurred:

- `rec_3840x2560_menu.png` — the camera menu/overlay showing the 3:2 movie size.
- `clip_properties.png` — the resulting MP4 properties (3840×2560, ~97.6 Mbps).
- `rear_lcd_fullframe.png` — the rear 3:2 LCD filling with the open-gate frame.

> Before committing any screenshot: blur the body serial and any file path, and keep
> EXIF out (re-export, don't copy the original).
