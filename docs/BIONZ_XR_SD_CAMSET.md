# BIONZ XR — SD card layout & `CAMSETxx.DAT` findings

**🌍 Language: English**

Research notes on the Sony A6700 (`ILCE-6700`, firmware 2.00) SD card
filesystem layout and the binary format of its saved camera-settings
profiles (`CAMSETxx.DAT`, written via *Menu → Setup → Setting Option →
Save/Load Settings → Save*). No firmware files are involved: a `CAMSETxx.DAT`
is a user-generated settings snapshot the camera itself writes to the card,
not anything extracted from the firmware image.

> ⚠️ **Status: re-verified directly against four real `CAMSETxx.DAT` files**
> (`CAMSET01`–`04`) read straight off the SD card this session — not just
> diffed once and left. The entry-count and "no checksum" findings in §3/§3bis
> are from an actual deterministic byte walk, re-run against all four
> samples with identical results each time. Everything else below (the
> per-offset diffs in §4) is still single-setting-unisolated correlation,
> not a confirmed field meaning — treat those as leads, not facts. **Do not
> write a `CAMSETxx.DAT` back to the card** — see §5; removing the checksum
> mystery doesn't make a write safe, most of the file is still undecoded.

## 1. SD card layout (`ILCE-6700`, firmware 2.00)

- **Root:** `BODYDATA.DAT` (~1.0 GB) is only the firmware update package used
  during an update to 2.00; safe to delete afterwards, and irrelevant to
  anything else on this page.
- **Binary index / thumbnail database** (`AVF_INFO/`):
  - `AVF_INFO/AVIN0001.INP` (1,382,400 bytes)
  - `AVF_INFO/AVIN0001.BNP` (1,382,400 bytes)
  - `AVF_INFO/AVIN0001.INT` (614,400 bytes)
- **XAVC / clip metadata** (`PRIVATE/M4ROOT/`):
  - `PRIVATE/M4ROOT/MEDIAPRO.XML` (71,984 bytes)
  - `PRIVATE/M4ROOT/CLIP/rec*.XML` (~2.1 KB per clip, `NonRealTimeMeta` schema
    v2.20)
- **User 3D LUTs:** `PRIVATE/M4ROOT/GENERAL/LUT/*.cube`,
  `PRIVATE/SONY/PRO/LUT/*.cube`.
- **Saved settings profiles:** `PRIVATE/SONY/SETTING/6700/CAMSET/CAMSET01.DAT`
  … `CAMSETxx.DAT` — 162,188 bytes (`0x2798C`) each.

## 2. `NonRealTimeMeta` clip signature observed (firmware 2.00)

A standard 4K 23.98p S-Log3 / S-Gamut3.Cine clip
(`rec20261127_0222M01.XML`) reports:

- Codec/FPS: `AVC100_3840_2160_H422P@L51`, `captureFps="23.98p"`,
  `formatFps="23.98p"`.
- Frame layout: `pixel="3840"`, `numOfVerticalLine="2160"`,
  `aspectRatio="16:9"` — i.e. the clip metadata itself reports 16:9, which is
  exactly what §4 below is diffing against (nothing here shows a 3:2 *video*
  clip, consistent with the HAITA lock documented in
  [`docs/RESULTS.en.md`](RESULTS.en.md) §2 and
  [`docs/BIONZ_XR_PTP_SDIO.md`](BIONZ_XR_PTP_SDIO.md) §2.4).
- Color/telemetry tables present: `s-log3-cine` / `s-gamut3-cine` (`rec709`
  coding), `ImagerControlInformation`, `LensControlInformation`,
  `DistortionCorrection`, `Gyroscope`, `Accelerometor`.

## 3. `CAMSETxx.DAT` binary structure (162,188 bytes)

- **Header** (`0x00`–`0x23`):
  - `0x00`–`0x0E`: ASCII `SONY1ILCE-6700`.
  - `0x15`–`0x23`: ASCII timestamp, `YYYYMMDD_HHMMSS` (e.g.
    `20261127_203007`).
- **Parameter stream** (`0x42`–`0x2798A`): TLV entries with a `cf 02`
  marker, field layout and entry count now decoded — see §3bis (**11,715
  entries**, not the earlier "11,728 occurrences" blind byte-scan count,
  which overcounts by matching `cf 02` inside opaque non-TLV spans too).
- **Trailer** (`0x27988`–`0x2798B`): **not a checksum** — corrected finding,
  see below. A deterministic TLV walk (`cf 02` marker, `elem_size:u8`,
  `reserved:u8`, `count:u16-LE`, `count×elem_size` value bytes,
  `param_id:u16-LE`; see §3bis) starting at `0x42` lands **exactly** at
  `0x2798A` in every `CAMSETxx.DAT` sample checked (`01`–`04`), decoding
  **11,715 entries** every time. The 2 bytes at `0x27988`–`0x27989` that
  looked like a per-file checksum (`7a 2e`, `ae 2a`, `7d 2e`, `e0 2a`) are
  simply the **last TLV entry's own `param_id`**, little-endian
  (`0x2E7A`, `0x2AAE`, `0x2E7D`, `0x2AE0`) — it varies between samples only
  because each camera state has a slightly different active-entry set, not
  because it's a hash over the file. `46 00` right after it is a genuine
  fixed end-of-stream sentinel, identical in all four samples. No checksum
  exists at this offset to reverse — the earlier "unknown checksum" framing
  was wrong.

### 3bis. TLV entry format and the repeated opaque blocks

Walking the stream with the length field (not a blind byte-scan for `cf 02`,
which overcounts — see note below) decodes cleanly as:

```
cf 02 | elem_size:u8 | reserved:u8(=0) | count:u16-LE
      | count × elem_size value bytes | param_id:u16-LE
```

The walk isn't *pure* TLV end to end: it has to skip past **25 opaque
(non-TLV) spans** per file to reach `0x2798A` cleanly — one big 3072-byte
block early (`0x75B`–`0x135B`), then **12 repeats** of a
`[4 bytes][~TLV entries][256 bytes]` pattern, evenly spaced roughly `0x2D36`
apart through the rest of the file. These spans are **byte-identical in
position and content** across all four samples (`CAMSET01`–`04`) tested so
far, including after the `CAMSET04` Picture-Profile-adjacent save (§4) —
every one of the twelve 256-byte sub-blocks has **zero changed bytes**
there. So whatever these repeated blocks hold, it isn't Photo/Video state,
aspect ratio, or the setting changed for `CAMSET04` — most likely a static
per-slot table (lens corrections, a fixed preset bank) unrelated to the
properties this project is chasing. A naive byte-scan for `cf 02` inside
these opaque spans overcounts matches (the earlier "11,728 occurrences"
figure in §3 above came from exactly that blind scan); the 11,715 figure
from the length-based walk is the reliable one.

## 4. Differential offsets observed (firmware 2.00)

Byte-for-byte diffs between saved-settings snapshots, same camera, same
firmware. Framed as "offset: value A → value B", A/B being the two profiles
compared.

### Photo 3:2 (`CAMSET01.DAT`) vs. Photo 16:9 (`CAMSET03.DAT`)

| Offset | 3:2 | 16:9 | Note |
|---|---|---|---|
| `0x1493` | `0x00` | `0x02` | Lines up with the PTP SDIO property `0xD211` (`aspect_ratio`) values `0x0001`/`0x0002` seen live over USB — see [`docs/BIONZ_XR_PTP_SDIO.md`](BIONZ_XR_PTP_SDIO.md) §2.4. Not the same numeric encoding (`0x00`/`0x02` here vs. `1`/`2` over PTP), so this is a *correlated* offset, not a confirmed direct mirror of the PTP property's raw value. |
| `0x1B9` | `0x01` | `0x02` | Unidentified. |

Remaining diffs between these two files (`0x20`–`0x23`, `0x39`, `0x27988`)
are the header timestamp and the final-entry `param_id` bytes from §3
(not a checksum, not ratio-related).

### Photo 3:2 (`CAMSET01.DAT`) vs. Video 16:9 (`CAMSET02.DAT`)

**28 bytes differ across 22 clusters** — the table below (`0x13E` through
`0x4263`) is the subset flagged in an earlier pass; full re-diff found 12
more single-byte clusters not previously listed:
`0x6C, 0x129, 0x192, 0x1DD, 0x1A69, 0x2967, 0x29BE, 0x2A5A, 0x3291, 0x39B7,
0x3FD5, 0x3FDE` (plus `0x21-0x23`/`0x39` timestamp and `0x27988-0x27989`
final-`param_id` noise, not counted as settings diffs).

| Offset | Photo 3:2 | Video 16:9 |
|---|---|---|
| `0x13E` | `0x03` | `0x02` |
| `0x354` | `0x00` | `0x01` |
| `0x250A` | `0x01` | `0x00` |
| `0x2613` | `0x02` | `0x01` |
| `0x264C` | `0x01` | `0x00` |
| `0x2E9E`–`0x2EA1` | `fb ff ff ff` | `00 00 00 00` |
| `0x4263` | `0x00` | `0x01` |

None of these are identified by name yet — they are candidate mode/feature
switches, nothing more, until each one is isolated (one setting changed at a
time, re-saved, re-diffed) rather than read off a single Photo-vs-Video
comparison that differs in more than just aspect ratio.

### `CAMSET04.DAT` (after a Picture-Profile-adjacent save) vs. `CAMSET01.DAT`

**51 bytes differ across 43 clusters** — markedly more than either
comparison above, and includes `0x1493` flipping `0x00`→`0x02` (the same
aspect-correlated byte from the Photo-3:2-vs-16:9 table), so this save
wasn't a pure profile-only change; something aspect/mode-adjacent moved too.
19 of the 43 clusters are new, not seen in any earlier diff:
`0xB4, 0x26A, 0x273, 0x14B7, 0x2540, 0x2552, 0x3A2C, 0x3A98, 0x3ACE, 0x3E10,
0x3E19, 0x3E22, 0x3E6A, 0x3E73, 0x3E7C, 0x3FF0, 0x3FF9, 0x4002, 0x4110`.

Checked against the 12 repeated `[256 bytes]` sub-blocks from §3bis: **zero
changed bytes in all twelve**, in both this comparison and every other
pairing tried. Whatever the Picture-Profile-adjacent setting touched, it's
in the small-entry TLV region alongside everything else, not in those
periodic blocks — ruling out "12 repeated blocks = 12 profile slots" as the
explanation for that structure.

## 5. Safety & workflow notes

- Keep every captured `CAMSETxx.DAT` as a read-only snapshot. Diff copies,
  never the card's working file.
- **Still no write path, even though §3's "checksum" turned out not to be
  one** — removing that mystery doesn't mean a write is safe. The dozens of
  unidentified TLV entries (§4) and the 12 opaque repeated blocks (§3bis)
  are still undecoded; nothing writes a `CAMSETxx.DAT` back to the card
  until far more of it is understood.
- For interactive property tests, prefer the live PTP SDIO path
  (`SetExtDevicePropValue`, `0x9205`, via `experiment_a6700.py
  --confirm-session-write`) — it is session-only and reverts on a cold boot,
  where a bad card write does not self-correct the same way.

## See also

- [`docs/BIONZ_XR_PTP_SDIO.md`](BIONZ_XR_PTP_SDIO.md) — the PTP/SDIO v300
  handshake and the live-verified `0xD211 aspect_ratio` values this page's
  §4 offset correlates with.
- [`docs/RESULTS.en.md`](RESULTS.en.md) — the HAITA application-layer 3:2
  lock, confirmed experimentally over PTP.
- [`RESEARCH.md`](../RESEARCH.md) — the original firmware-side findings
  (display panels, the `dmmwb` buffer calculation) this SD-card research is
  a card-level counterpart to.
