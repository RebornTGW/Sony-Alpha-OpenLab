# BIONZ XR — PTP / SDIO v300, and why BIONZ X stalls on the old path

**🌍 Language: English**

Read-only protocol notes behind `sdio_probe.py` / `scripts/probe_a6700_sdio.py`.
No firmware bytes; PTP/ISO 15740 and the independently documented Sony "SDIO"
vendor extension are protocol constants, not firmware content.

> ⚠️ **A note on the numbers in this document.** Every figure below is the one
> actually **observed live** on our test unit (see
> [`docs/RESULTS.en.md`](RESULTS.en.md) and the commit history of
> `probe_a6700.py`). A few counts we were asked to publish in an earlier draft
> of this page — "77 supported operations / 58 Sony `0x92xx` opcodes / 45
> events / 351 decoded properties" — do **not** match what the camera actually
> reports and have been left out rather than printed as fact. If you capture a
> `GetDeviceInfo` + `GetAllExtDevicePropInfo` dump that shows different counts
> (different firmware, different camera mode, a different body entirely),
> that's a real data point — open an issue with the `--dump-bin` output
> attached and we'll update this table.

## 1. Why BIONZ X (`054C:0E76`, `VREQ_START_SENSER`) stalls on a BIONZ XR body

The legacy Sony "Senser" path (`host-injector`'s target) is a **Mass Storage
vendor extension**: a vendor SCSI CDB (`0x7a`) sent over the MSC bulk
endpoints while the camera presents itself as `054C:0E76`. It is how BIONZ X
bodies (A6400, A6600, A6100, A7 III, A7C, …) expose their service mode.

BIONZ XR bodies — the A6700 among them — simply don't answer that vendor CDB
the same way: a `VREQ_START_SENSER` control transfer against a BIONZ XR body
comes back as a USB **Pipe/STALL** error, not a protocol-level rejection. That
is consistent with the processor generation having moved its remote-control
surface to a different transport entirely (see §2), rather than BIONZ XR
running a patched/incompatible version of the same Senser service. This is
exactly why `host-injector/src/camera.rs` refuses outright on a known BIONZ X
PID before sending a single vendor packet — the two protocol families are not
interchangeable, and guessing would mean sending unverified control transfers
at hardware we have no basis to assume will handle them safely.

## 2. The verified BIONZ XR path: PTP + Sony "SDIO" v300

BIONZ XR exposes its remote-control surface over standard **PTP** (ISO 15740)
container framing, plus a Sony vendor extension nicknamed "SDIO" in the
community. On the A6700 this is reachable as a **separate USB PID**:

| PID | USB mode | Used by |
|---|---|---|
| `054C:0E78` | **PC Remote** | `probe_a6700.py`, `sdio_probe.py`, `multi_exposure.py` |
| `054C:0E76` | Mass Storage (BIONZ X Senser path) | `host-injector` (refuses on BIONZ XR — see §1) |

### 2.1 Verified handshake sequence (ILCE-6700, firmware 2.00)

```
OpenSession(0x1002, [1])
  -> OK
GetDeviceInfo(0x1001)
  -> OK, ~826 bytes* dataset (manufacturer/model/firmware, operations,
     events, device properties, formats)
SDIO_Connect(0x9201, [1,0,0])   -> OK, 8-byte DATA phase
SDIO_Connect(0x9201, [2,0,0])   -> OK, 8-byte DATA phase
SDIO_GetExtDeviceInfo(0x9202, [0x012C])
  -> OK, ~826 bytes
SDIO_Connect(0x9201, [3,0,0])   -> OK, 8-byte DATA phase
SDIO_GetAllExtDevicePropInfo(0x9209, [0,0])
  -> OK, ~8019 bytes, 122 active property records (Video mode)
```

\* `GetDeviceInfo` and `SDIO_GetExtDeviceInfo` land on close to the same byte
count on our unit; they are two different datasets (standard PTP vs. the Sony
extension) that happen to be similar in size here, not the same response.

Each `SDIO_Connect` phase *must* have its 8-byte DATA phase consumed before
reading the RESPONSE container — `PtpUsbDevice.transaction()` in
`probe_a6700.py` (reused by `sdio_probe.py`) does this automatically. Getting
this wrong is the most common way to desync the whole session and start
seeing garbage on the next transaction.

### 2.2 What `GetDeviceInfo` reports, live

- **61 vendor opcodes** in the `0x92xx` range (the Sony "SDIO" space),
  confirmed present in the `OperationsSupported` array.
- `GetExtDevicePropValue (0x9204)` is listed as supported but actually
  returns **`0x2005` Operation Not Supported** when called on this v300
  dataset — current values have to be read out of the
  `GetAllExtDevicePropInfo (0x9209)` stream instead (`current_value_in_stream`
  in `probe_a6700.py`, reused structurally by `sdio_probe.parse_all_ext_prop_info`).

### 2.3 The `0x9209` property-record format (what `sdio_probe.py` decodes)

Each record in the flat `GetAllExtDevicePropInfo` stream is, byte for byte,
as verified against a live capture:

```
code        u16   DevicePropCode (e.g. 0xD211 aspect_ratio)
type        u16   PTP datatype (0x0001..0x0008 int/uint, 0xFFFF = UTF-16LE
                   string; bit 0x4000 set = array of the base type — a
                   standard PTP convention, not Sony-specific)
getset      u8    0 = Get only, 1 = Get/Set
enable      u8    IsEnable flag (whether the property is currently exposed
                   in the camera's present mode)
(extra)     u8    one Sony-specific byte with no effect observed on decode;
                   skipped. Without it every multi-byte enum (e.g.
                   still_capture_mode's 26-entry list) comes out misaligned.
default     DTS   FactoryDefault, as `type`
current     DTS   CurrentValue, as `type`
form        u8    0x00 none, 0x01 range, 0x02 enum
  [range]         min, max, step — all as `type`
  [enum]          u16 count + count × `type` — the **Supported** values list
```

That is the structure `sdio_probe.parse_ext_device_prop_record` decodes, and
it is the **only** structure confirmed on real hardware so far: every record
in a live `0x9209` capture round-trips cleanly reading exactly one enum list
per record, nothing more.

**On the "dual Supported+Available enum list" idea.** We were asked to
document and implement a `form == 0x02` variant with a *second* trailing
list — a per-property "currently available" subset on top of the "supported"
one. That shape is plausible (some SDK-level Sony tooling exposes a similar
concept), but nothing in our own captures shows it, and parsing a list that
isn't actually there would silently corrupt every record after it in the
stream. `sdio_probe.py` implements it anyway, strictly **opt-in**
(`--assume-dual-enum`) and clearly marked unverified in its own docstring —
pointing it at a real dump and comparing `--parse-bin` output with and without
the flag is the way to find out whether a given firmware actually has it, not
asserting that it does.

### 2.4 `0xD211` aspect_ratio — the property this project cares about

`Get/Set`, `enabled=1`, form **none** (plain `UINT16`, no enum on this body —
*not* a form-0x02 enum property, despite aspect ratio reading like a natural
fit for one).

| Mode | `CurrentValue` |
|---|---|
| Photo | `1` (3:2) |
| Video | `2` (16:9) |

Writing `1` while in Video mode returns PTP `OK` and is then **silently
ignored** on re-read — the HAITA Feature Manager's
`REC_MOVIE_ASPECT_RATIO_NOT_16_9` gate sits in `appFw.so`, above PTP. See
[`docs/RESULTS.en.md`](RESULTS.en.md) §2 for the full experiment. This is why
the project's volatile-RAM Open Gate research (`host-injector`,
`target-helper`) targets the BIONZ XR encoder pipeline directly rather than
trying to find a magic property write — the lock is enforced one layer above
where any PTP property write can reach.

### 2.4bis Cross-check against `CAMSETxx.DAT` (SD card settings profiles)

A separate, card-level research pass diffed saved settings profiles
(`CAMSETxx.DAT`, written by *Menu → Setup → Setting Option → Save/Load
Settings → Save*) between Photo 3:2 and Photo 16:9. It found a byte at
offset `0x1493` that flips `0x00` ↔ `0x02` across exactly that change —
*correlated* with, but not a confirmed direct mirror of, the `0xD211`
`aspect_ratio` values (`1`/`2`) seen live over PTP above: the two don't share
the same raw encoding (`0x00`/`0x02` on the card vs. `1`/`2` over PTP), and
the card-side offset has not been independently re-verified in this session
the way the PTP handshake has. See
[`docs/BIONZ_XR_SD_CAMSET.md`](BIONZ_XR_SD_CAMSET.md) for the full writeup,
the `CAMSETxx.DAT` binary layout, and why its trailer checksum blocks any
write-back for now.

### 2.5 `0xD241` / `0xD242` — movie format/quality stay inside 16:9

`0xD241 file_format_movie` and `0xD242 recording_setting_movie` both return an
**empty** descriptor via `GetExtDevicePropDesc (0x9203)` even while the camera
is in Video mode — but they **are** present in the `0x9209` stream, with real
`CurrentValue`s. Every enum/range value seen on either property stays inside
the set of modes the camera's menu exposes for 16:9 recording; neither
property is where a 3:2 "Open Gate" mode would surface even if the HAITA gate
above let a write through. Combined with §2.4, this is the evidence trail
that led the project away from "find the right property" and toward the
RAM-descriptor research tracked in `host-injector`/`target-helper`.

## 3. Using `sdio_probe.py`

```bash
# Live camera, read-only. Prints the decoded video-related properties.
python scripts/probe_a6700_sdio.py

# Save the raw 0x9209 payload for later / for sharing without a camera.
python scripts/probe_a6700_sdio.py --dump-bin a6700_200_video.bin

# Decode a saved dump completely offline — no USB, no camera.
python scripts/probe_a6700_sdio.py --parse-bin a6700_200_video.bin --verbose

# Export the decoded property map as JSON.
python scripts/probe_a6700_sdio.py --parse-bin a6700_200_video.bin --json props.json
```

Strictly read-only: the only opcodes ever sent are OpenSession, CloseSession,
GetDeviceInfo, SDIO_Connect, SDIO_GetExtDeviceInfo, and
SDIO_GetAllExtDevicePropInfo — see `probe_a6700.READ_ONLY_OPS`, which
`sdio_probe.py` imports rather than redefining.

## See also

- [`docs/BIONZ_XR_SD_CAMSET.md`](BIONZ_XR_SD_CAMSET.md) — the SD card
  layout and `CAMSETxx.DAT` settings-profile findings this page's §2.4bis
  cross-checks `0xD211` against.
- [`probe_a6700.py`](../probe_a6700.py) — the original live-handshake probe
  this module reuses the transport and dataset parsers from.
- [`docs/RESULTS.en.md`](RESULTS.en.md) — the multi-exposure success and the
  Open Gate 3:2 application-layer lock, both validated live.
- [`docs/PROTOCOL.en.md`](PROTOCOL.en.md) — the broader PTP/"SDIO" protocol
  architecture.
- [`docs/ROADMAP.en.md`](ROADMAP.en.md) §4 — the separate BIONZ X research
  track this probe does **not** touch.
