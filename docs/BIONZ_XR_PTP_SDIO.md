# BIONZ XR — PTP / SDIO v300, and why BIONZ X stalls on the old path

**🌍 Language: English**

Read-only protocol notes behind `sdio_probe.py` / `scripts/probe_a6700_sdio.py`.
No firmware bytes; PTP/ISO 15740 and the independently documented Sony "SDIO"
vendor extension are protocol constants, not firmware content.

> ⚠️ **A note on the numbers in this document.** Every figure below is the one
> actually **observed live** on our test unit (see
> [`docs/RESULTS.en.md`](RESULTS.en.md) and the commit history of
> `probe_a6700.py` / `sdio_probe.py`). An earlier draft of this page said a
> "351 decoded properties" / "dual Supported+Available enum list" claim
> didn't match what we could verify — that was true *at the time*: the file
> we had couldn't be parsed under any layout tried. It's since been
> re-verified properly: a live re-capture, cross-referenced record-by-record
> against the independently-decoded `SDIO_GetExtDeviceInfo (0x9202)`
> property-code list, confirms **351 properties and the dual-list shape are
> both real** — see §2.3. The `77` total ops / `58` vendor-`0x92xx`-only /
> `45` events split from that same earlier draft is still unconfirmed (our
> own capture says `61` vendor `0x92xx` opcodes, see §2.2) and is left out
> until it's checked the same way.

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
  -> OK, 9731 bytes, 351 property records (re-confirmed live, see §2.3)
```

An earlier capture in a different camera mode read ~8019 bytes / 122 active
properties instead — the handshake and opcodes are identical either way;
only the property count moves with however many properties the camera's
current mode exposes.

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

**How this was actually verified, not just asserted:** `SDIO_GetExtDeviceInfo
(0x9202)` turns out to hold two flat arrays — `version(u16)=0x012C`,
`count1(u16)=351`, `reserved(u16)=0`, `[351 DevicePropCodes]`,
`count2(u16)=57`, `reserved(u16)=0`, `[57 control/trigger codes]` — exactly
`6 + 351×2 + 2 + 2 + 57×2 = 826` bytes, no leftover. That 351-code list is in
the *same order* the properties appear in `0x9209`. Walking `0x9209` and
finding each of those known codes in sequence pins down every record's exact
start and end **without assuming a field layout** — and three records of
three different shapes (none / range / enum) each decoded with **zero
leftover bytes** once the layout below was tried. That's the confirmation,
not a guess that happened to not crash.

**`0x9209` stream header**, 8 bytes before the first record:

```
count       u32   total property records (351 on our unit)
reserved    u32   0 on every capture so far
```

**Each record**, verified live (SDK version `0x012C`, i.e. SDIO v300):

```
code        u16   DevicePropCode (e.g. 0xD211 aspect_ratio)
type        u16   PTP datatype (0x0001..0x0008 int/uint, 0xFFFF = UTF-16LE
                   string; bit 0x4000 set = array of the base type — a
                   standard PTP convention, not Sony-specific)
getset      u8    0 = Get only, 1 = Get/Set
enable      u8    IsEnable flag (whether the property is currently exposed
                   in the camera's present mode)
default     DTS   FactoryDefault, as `type` — directly after `enable`, no
                   padding byte (that padding is a v200 quirk, see below)
current     DTS   CurrentValue, as `type`
form        u8    0x00 none, 0x01 range, 0x02 enum
  [range]         min, max, step — all as `type`
  [enum]          u16 count1 + count1 × `type`  ("Supported" values)
                  u16 count2 + count2 × `type`  ("Available" values —
                  confirmed real: on a live capture, 0xD211 aspect_ratio
                  decodes as Supported=[1,3,2,4], Available=[1,3,2,4],
                  current=2, the record ending exactly where the next known
                  code begins)
```

This is `sdio_probe.parse_ext_device_prop_record`'s default behavior. The
**older SDIO v200** dataset (SDK version `0x00C8`) uses a different shape —
one padding byte between `enable` and `default`, and only a *single* enum
list, no stream header before the first record — reachable with
`sdio_probe.py`'s `--single-enum` flag for an older dump.

### 2.4 `0xD211` aspect_ratio — the property this project cares about

`Get/Set`, `enabled=1`, `UINT8`, form **enum** — Supported=`[1,3,2,4]`,
Available=`[1,3,2,4]` on our unit (see §2.3; values `3` and `4` have not
been identified by name).

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

# An older SDIO v200 (SDK 0x00C8) dump instead of v300 (see §2.3):
python scripts/probe_a6700_sdio.py --parse-bin legacy_v200.bin --single-enum
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
