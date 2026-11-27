# BIONZ XR — SD card layout & `CAMSETxx.DAT` findings

**🌍 Language: English**

Research notes on the Sony A6700 (`ILCE-6700`, firmware 2.00) SD card
filesystem layout and the binary format of its saved camera-settings
profiles (`CAMSETxx.DAT`, written via *Menu → Setup → Setting Option →
Save/Load Settings → Save*). No firmware files are involved: a `CAMSETxx.DAT`
is a user-generated settings snapshot the camera itself writes to the card,
not anything extracted from the firmware image.

> ⚠️ **Status: research notes, not independently re-verified in this
> session.** These offsets come from diffing `CAMSETxx.DAT` save files
> against each other, not from a live PTP/USB capture — nobody here has
> re-run that byte-diff against our own card dump. Treat every offset below
> the same way the rest of this repo treats any unverified claim: a lead to
> go check, not a fact to build a write path on. In particular, **do not use
> these offsets for a blind write-back** — the trailer checksum (§3) is not
> understood yet, and writing a `CAMSETxx.DAT` with a bad checksum back to
> the card is a real way to confuse the camera's settings loader.

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
- **Parameter stream** (`~0x42`–`0x27987`): variable-length / TLV-like
  entries with a recurring `cf 02` marker — 11,728 occurrences counted in one
  `CAMSET01.DAT` sample. The exact field boundaries inside this region are
  not decoded; the offsets in §4 are single-byte diffs between whole-file
  dumps, not a parsed field layout.
- **Trailer** (`0x27988`–`0x2798B`): a 2-byte value at `0x27988`–`0x27989`
  that changes with file content (`7a 2e` in one `CAMSET01.DAT` sample,
  `ae 2a` in a `CAMSET02.DAT` sample, `7d 2e` in a `CAMSET03.DAT` sample),
  followed by a constant end marker `46 00`. Standard whole-file or
  header-offset CRC-16 and simple 8/16/32-bit sums were tried and did **not**
  reproduce it — the checksum scope and algorithm are still unknown. This is
  exactly the kind of gap the project's "refuses to guess" rule
  (see `probe_a6700.py`'s module docstring) exists for: until the algorithm
  is known, nothing writes this trailer back.

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
are the header timestamp and the trailer check bytes from §3, not
ratio-related.

### Photo 3:2 (`CAMSET01.DAT`) vs. Video 16:9 (`CAMSET02.DAT`)

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

## 5. Safety & workflow notes

- Keep every captured `CAMSETxx.DAT` as a read-only snapshot. Diff copies,
  never the card's working file.
- **Do not write an unverified checksum back to the card** — see §3. A write
  path needs the real trailer algorithm first, not a guess that happens to
  look plausible on one sample.
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
