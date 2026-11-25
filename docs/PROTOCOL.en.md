# PTP / "SDIO" remote-control protocol — Sony A6700 (ILCE-6700)

**🌍 Language: English · [Français](PROTOCOL.md)**

Technical description of the communication protocol between a host (PC / smartphone)
and the **Sony A6700** body, as reconstructed by **independent static analysis**.
Reference document for `probe_a6700.py`.

> This document contains no file or excerpt from the Sony firmware. The opcodes and
> property codes are **protocol constants** (PTP / ISO 15740 and the Sony vendor
> space), used for interoperability purposes.

---

## 1. Transport stack

Over USB, the body exposes a **Still Image / PTP** interface (USB class `0x06`) when
set to **PC Remote** (or **PTP**) USB connection mode. The same application protocol
is carried over two channels:

| Channel | Transport | Use |
|---|---|---|
| **USB** | PTP over bulk-in / bulk-out (Still Image class) | wired PC Remote |
| **Network (PTP/IP)** | TCP sockets, multi-session, pairing | Wi-Fi / Imaging Edge |

`probe_a6700.py` implements the **USB** channel only.

### PTP/USB container

Each message is a 12-byte header container + payload:

```
offset 0  : uint32  length          (total length, header included)
offset 4  : uint16  type            1=Command, 2=Data, 3=Response, 4=Event
offset 6  : uint16  code            opcode (Command) or response code (Response)
offset 8  : uint32  transaction_id
offset 12 : payload                 parameters (Command) or data (Data)
```

A transaction = **Command phase** (host → camera) → optional **Data phase** →
**Response phase** (camera → host, `response_code`, `0x2001` = OK). The 3-phase split
also appears on the firmware side in the `cmd_* / dat_* / res_*` handlers.

---

## 2. Software architecture (camera side)

The remote-control chain is **layered**:

```
 Application (menus, model capabilities)
      │
      ▼
 Vendor "Camera Remote" layer      ── MrpwSDIO* operations (0x92xx)
      │                                liveview, transfer, extended properties
      ▼
 Plug-in / opcode registry         ── handlers registered per operation code
      │
      ▼
 Base PTP engine                   ── operation table + 3-phase cmd/dat/res
      │                                standard operations 0x10xx
      ▼
 Transports                        ── USB (Still Image bulk) / PTP-IP (socket)
```

- **Standard operations** (0x1001–0x101B) are the PTP core: session, device info,
  object enumeration and transfer.
- **Sony vendor "SDIO" operations** (from `0x9201`) add extended capability
  discovery, read/write of shooting properties, triggering, liveview, FTP/HTTP
  transfer, etc.
- **Extension commands** are wrapped in two dedicated vendor operations: `0x9280`
  (*Send Ext Command*) and `0x9281` (*Get Ext Response*).

---

## 3. Operations (opcodes)

### 3.1 Standard PTP (ISO 15740)

| Opcode | Operation | Access |
|---|---|---|
| 0x1001 | GetDeviceInfo | read |
| 0x1002 | OpenSession | session |
| 0x1003 | CloseSession | session |
| 0x1004 | GetStorageIDs | read |
| 0x1005 | GetStorageInfo | read |
| 0x1006 | GetNumObjects | read |
| 0x1007 | GetObjectHandles | read |
| 0x1008 | GetObjectInfo | read |
| 0x1009 | GetObject | read |
| 0x100A | GetThumb | read |
| 0x100D | SendObject | **write** |
| 0x101B | GetPartialObject | read |

### 3.2 Sony vendor "SDIO" (excerpt)

Contiguous opcode space from `0x9201`. Operations in **bold** are used (read-only) by
`probe_a6700.py`; those marked *(write)* are never used.

| Opcode | Operation | Role |
|---|---|---|
| **0x9201** | `Connect` | vendor session handshake |
| **0x9202** | `GetExtDeviceInfo` | remote capabilities |
| **0x9203** | `GetExtDevicePropDesc` | descriptor of one property |
| 0x9204 | `GetExtDevicePropValue` | value of one property (read) |
| 0x9205 | `SetExtDevicePropValue` | write a property *(write)* |
| 0x9206 | `GetControlDeviceDesc` | descriptor of control codes |
| 0x9207 | `ControlDevice` | actuation / triggering *(write)* |
| 0x9208 | `GetAllExtDeviceProp` | dump of all property values |
| 0x9209 | `GetAllExtDevicePropInfo` | dump of all property descriptors |
| 0x920A | `GetCautionInfo` | messages / warnings |
| 0x9210 | `OpenSession` (SDIO) | vendor session |
| 0x9211 | `GetPartialLargeObject` | partial transfer of large objects |
| 0x9213 | `GetDeviceLog` | logs |
| 0x9214 | `SetRemoteSdkInfo` | host SDK identification |
| 0x9216 | `GetVenderCodeVersion` | vendor code version |
| 0x921A | `UploadData` | host → camera upload *(write)* |
| 0x921D | `DownloadData` | camera → host download |
| 0x9238 | `GetOSDImage` | liveview OSD image |
| … | (space up to ~0x923A) | FTP, presets, firmware, sync, etc. |
| 0x9280 | *Send Ext Command* | extension-command transport *(write)* |
| 0x9281 | *Get Ext Response* | extension-response transport |

---

## 4. Properties (`DevicePropCode`)

The shooting dialogue is **generic and data-driven**: the host passes a
`DevicePropCode` (uint16) as a parameter to a `GetExtDevicePropDesc / Value` or
`SetExtDevicePropValue` operation. The returned descriptor states the type, access
(read-only / read-write) and value range.

Ranges:

| Range | Nature |
|---|---|
| 0x50xx | standard PTP properties |
| 0xD1xx | Sony vendor properties (settings, statuses) |
| 0xD2xx | Sony vendor properties (settings + "buttons" 0xD2Cx–0xD2Fx) |
| 0xD3xx | system control codes (`ControlDevice`) |

The exhaustive list (**386 codes**) with symbolic names is in
[`DEVICE_PROPERTIES.en.md`](DEVICE_PROPERTIES.en.md).

### Reference codes

| Code | Name | Note |
|---|---|---|
| `0x5013` | `still_capture_mode` | Drive mode: single / continuous / self-timer / **bracket** |
| `0xD211` | `aspect_ratio` | 3:2 / 16:9 / 4:3 / 1:1 (movie locked to 16:9 by model capability) |
| `0xD241` | `file_format_movie` | XAVC HS / S / S-I |
| `0xD242` | `recording_setting_movie` | resolution / bitrate |
| `0xD286` | `recording_frame_rate_setting_movie` | movie frame rate |
| `0xD20D` / `0xD21E` | `shutter_speed` / `iso_sensitivity` | exposure |

### Triggering (⚠️ write — never issued by this tool)

Triggering is **not** a classic property write but goes through `ControlDevice`
(0x9207) on "button" codes:

| Code | Name | Effect |
|---|---|---|
| `0xD2C1` | `s1_button` | half-press (AF) |
| `0xD2C2` | `s2_button` | full-press (photo release) |
| `0xD2E6` | `s1_and_s2_button` | S1 + S2 |
| `0xD2C8` | `movie_rec_button` | movie record start/stop |

---

## 5. Typical dialogue sequence (USB)

```
OpenSession(0x1002)
  └─ Connect(0x9201)                 vendor session handshake
       └─ SetRemoteSdkInfo(0x9214)   host identification
            └─ GetExtDeviceInfo(0x9202) / GetAllExtDevicePropInfo(0x9209)
                 └─ GetExtDevicePropDesc(0x9203, prop=0x5013/0xD211/0xD241…)   [read]
                      └─ (optional, write) SetExtDevicePropValue(0x9205, …)
                           └─ (optional, write) ControlDevice(0x9207, S1→S2)
                                └─ GetObject / GetPartialLargeObject
CloseSession(0x1003)
```

`probe_a6700.py` stops at the **read** steps (up to `GetExtDevicePropDesc`), then
closes the session.

> ✅ **Validated live — A6700, firmware 2.00.** This exact handshake was confirmed on
> real hardware (PID `0x0E78`, PC Remote mode): `SDIO_Connect(0x9201)` ph1/ph2/ph3
> each return `OK` with an 8-byte DATA phase; `SDIO_GetExtDeviceInfo(0x9202)` returns
> ~826 bytes; `GetExtDevicePropDesc(0x9203)` returns a decodable `DevicePropDesc`
> (e.g. 66 bytes for `still_capture_mode`, 12 bytes for `aspect_ratio`, and an empty
> descriptor for `file_format_movie` while the body is in Photo mode). Each
> `SDIO_Connect` phase returns a short DATA payload that must be consumed before the
> RESPONSE, and `param2`/`param3` must be `0`.

### Control & write results (validated live, A6700 fw 2.00)

Session-only writes were confirmed on real hardware:

- **Triggering works.** `ControlDevice(0x9207)` on `s1_button (0xD2C1)`,
  `s2_button (0xD2C2)` and `movie_rec_button (0xD2C8)` (press value `2`, release `1`)
  all return `OK`. Full USB control of multi-frame capture and movie start/stop is
  functional.
- **`GetExtDevicePropValue (0x9204)` is not supported** on the v300 dataset
  (`0x2005`); current values are read from the `GetAllExtDevicePropInfo (0x9209)`
  stream instead (~8019 bytes, 122 active properties in Video mode).
- **Application-level HAITA lock on `aspect_ratio (0xD211)`.**
  `SetExtDevicePropValue(0xD211) <- 1` (3:2) returns `OK`, but the value re-read from
  `0x9209` stays `2` (16:9) in Video mode. The command is **accepted then silently
  ignored**: the HAITA Feature Manager (`REC_MOVIE_ASPECT_RATIO_NOT_16_9`) enforces
  16:9 for movie in `appFw.so`, above the PTP layer. Open Gate 3:2 video is therefore
  **not** reachable through a property write alone.

---

## 6. Extraction methodology

The information above comes from static analysis (AArch64 disassembly, ELF
inspection) of the camera's application libraries:

- **opcode ↔ operation** mapping: `Mrpw*EntryManager::makeInstance` factory tables
  (vtable loaded via the GOT);
- **code ↔ property name** mapping: the remote-property registration table (the name
  string is loaded just before the code assignment);
- extension-command transport: the `0x9280` / `0x9281` dispatch in the
  extension-command dispatcher.

No binary firmware data is reproduced or redistributed in this repository.
