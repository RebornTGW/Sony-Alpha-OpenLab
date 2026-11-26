#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ram_opengate.py - volatile RAM Open Gate research helper for the Sony A6700.

Why PTP alone does not work
---------------------------
On A6700 firmware 2.00 the movie aspect ratio is NOT gated by the USB/PTP layer.
Setting PTP `aspect_ratio (0xD211)` to 3:2 is ACCEPTED (the SetExtDevicePropValue
returns OK) but then IGNORED while recording: the application framework re-asserts
16:9. The lock lives in the HAITA capability layer inside `appFw.so`, where a
data-driven feature check (`REC_MOVIE_ASPECT_RATIO_NOT_16_9`) refuses any non-16:9
movie aspect. So no property write exposed over PTP can produce 3:2 video.

What the volatile RAM approach targets
---------------------------------------
On BIONZ XR the recorded frame geometry ends up as a plain height word fed to the
movie encoder in `libmpr.so`. The research idea is to change that height word in
RAM only (3840x2160 height #0x870 -> 3840x2560 #0xa00), downstream of the HAITA
menu gate, so nothing persistent is touched. It is volatile: a power-off or
battery pull restores the stock firmware image.

Channel: USB Mass Storage (SCSI Bulk-Only Transport) vendor commands - the
open-source Sony updater / PMCA-RE style service transport (A6700 Mass Storage
PID 0x0E76). This file is ORIGINAL code (MIT): it reimplements the generic
USB-MSC BOT framing and the ARM64 signature scan, and leaves the Sony vendor
memory CDBs as clearly-marked constants to confirm on hardware. It contains NO
firmware bytes and NO GPL code.

Safety:
  --verify-only (default): STRICTLY read-only. Locates the encoder height word by
    signature and checks the stock bytes - writes nothing.
  --probe-msc: STRICTLY read-only. Sends standard, safe SCSI commands (INQUIRY,
    READ CAPACITY, TEST UNIT READY) to confirm BOT framing responds, before any
    vendor memory CDB is ever used.
  --confirm-ram-write: opt-in. Backs up the original RAM bytes, applies the
    volatile patch (#0x870 -> #0xa00), reads back to verify; gone at power-off.
  --restore: writes the backed-up / stock bytes back, no reboot.
"""
from __future__ import annotations

import argparse
import struct
import sys

try:
    import usb.core
    import usb.util
except ImportError:
    sys.exit("[ERROR] pyusb missing: pip install pyusb")

SONY_VID = 0x054C
A6700_MSC_PID = 0x0E76            # A6700 in USB Mass Storage mode
USB_CLASS_MSC = 0x08             # USB Mass Storage interface class

# Stock encoder height word (movz #0x870 = 2160) and the Open Gate value
# (#0xa00 = 2560); the width store is #0xf00 = 3840. The RAM site is resolved by
# signature scan, never stored as firmware bytes.
STOCK_HEIGHT = 0x0870
OPENGATE_HEIGHT = 0x0A00
OPENGATE_WIDTH = 0x0F00

# ARM64 MOVZ (wide immediate), LSL #0. Encoding: sf 10 100101 hw imm16 Rd, with
# imm16 in bits [20:5] and Rd in [4:0]. The 32-bit base opcode is 0x52800000.
# MOVZ_MASK ignores the sf bit (W vs X register), hw, Rd and imm16, so we can
# match "movz <w|x>reg, #imm, lsl #0" for any destination register.
MOVZ_LSL0_BASE = 0x52800000
MOVZ_MASK = 0x7FE00000

# --- Sony vendor memory CDBs (CONFIRM ON HARDWARE from the open updater proto) ---
# Not shipped with working opcodes on purpose: fill these from the open-source
# transport before use. Left None so the tool refuses rather than guesses.
# Each is a callable that builds the raw SCSI CDB from an address + length, e.g.
#   VENDOR_MEM_READ_CDB  = lambda addr, length: bytes([0xC0]) + struct.pack(">II", addr, length)
#   VENDOR_MEM_WRITE_CDB = lambda addr, length: bytes([0xC1]) + struct.pack(">II", addr, length)
VENDOR_MEM_READ_CDB = None        # lambda addr, length: <cdb bytes>
VENDOR_MEM_WRITE_CDB = None       # lambda addr, length: <cdb bytes>


class MscError(RuntimeError):
    pass


def _is_movz_imm(word: int, imm16: int) -> bool:
    """True if `word` is an ARM64 'movz <reg>, #imm16, lsl #0' instruction."""
    return (word & MOVZ_MASK) == MOVZ_LSL0_BASE and ((word >> 5) & 0xFFFF) == imm16


class MscDevice:
    """Minimal USB Mass Storage Bulk-Only Transport (original implementation)."""

    def __init__(self, dev, ep_in, ep_out):
        self.dev, self.ep_in, self.ep_out = dev, ep_in, ep_out
        self._tag = 0

    @classmethod
    def open(cls, pid=A6700_MSC_PID):
        # Prefer the libusb-package backend on Windows (same as probe_a6700.py).
        try:
            import libusb_package
            backend = libusb_package.get_libusb1_backend()
        except ImportError:
            backend = None
        kwargs = {"idVendor": SONY_VID, "idProduct": pid}
        if backend is not None:
            kwargs["backend"] = backend
        dev = usb.core.find(**kwargs)
        if dev is None:
            raise MscError(
                f"No Sony MSC device (VID 0x{SONY_VID:04X} PID 0x{pid:04X}). "
                "Set the camera USB mode to Mass Storage.")
        dev.set_configuration()
        intf = None
        for cfg in dev:
            for i in cfg:
                if i.bInterfaceClass == USB_CLASS_MSC:
                    intf = i
                    break
        if intf is None:
            raise MscError("No Mass Storage interface (class 0x08) found.")
        ep_in = usb.util.find_descriptor(intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        ep_out = usb.util.find_descriptor(intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
        return cls(dev, ep_in, ep_out)

    def _cbw(self, cdb, data_len, direction_in):
        self._tag = (self._tag + 1) & 0xFFFFFFFF
        flags = 0x80 if direction_in else 0x00
        cbw = struct.pack("<IIIBBB", 0x43425355, self._tag, data_len, flags, 0,
                          len(cdb)) + bytes(cdb).ljust(16, b"\x00")
        self.ep_out.write(cbw, 4000)

    def _csw(self):
        csw = bytes(self.ep_in.read(13, 4000))
        if len(csw) != 13 or csw[:4] != b"USBS":
            raise MscError("bad CSW")
        return csw[12]  # status byte (0 = ok)

    def command(self, cdb, data_len=0, direction_in=True):
        self._cbw(cdb, data_len, direction_in)
        data = b""
        if data_len and direction_in:
            data = bytes(self.ep_in.read(data_len, 6000))
        status = self._csw()
        if status != 0:
            raise MscError(f"CSW status {status}")
        return data

    def scsi_try(self, cdb, data_len=0):
        """Issue one read-only SCSI command, returning (status, data) WITHOUT
        raising on a non-zero SCSI status (for the probe). status None = no reply."""
        try:
            self._cbw(cdb, data_len, True)
            data = b""
            if data_len:
                try:
                    data = bytes(self.ep_in.read(data_len, 6000))
                except usb.core.USBError:
                    data = b""
            return self._csw(), data
        except (usb.core.USBError, MscError):
            return None, b""

    # --- standard, safe SCSI probes (read-only) ---
    def inquiry(self):
        return self.scsi_try(bytes([0x12, 0, 0, 0, 36, 0]), 36)

    def test_unit_ready(self):
        return self.scsi_try(bytes([0x00, 0, 0, 0, 0, 0]), 0)

    def read_capacity10(self):
        return self.scsi_try(bytes([0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 8)

    # --- vendor memory access (needs the CDBs above) ---
    def mem_read(self, addr, length):
        if VENDOR_MEM_READ_CDB is None:
            raise MscError("VENDOR_MEM_READ_CDB not configured (see file header).")
        cdb = VENDOR_MEM_READ_CDB(addr, length)
        return self.command(cdb, length, direction_in=True)

    def mem_write(self, addr, data):
        if VENDOR_MEM_WRITE_CDB is None:
            raise MscError("VENDOR_MEM_WRITE_CDB not configured (see file header).")
        cdb = VENDOR_MEM_WRITE_CDB(addr, len(data))
        self._cbw(cdb, len(data), False)
        self.ep_out.write(data, 6000)
        if self._csw() != 0:
            raise MscError("write CSW error")

    def close(self):
        usb.util.dispose_resources(self.dev)


def find_libmpr_height_site(dev, scan_start=None, scan_size=None,
                            chunk=0x10000, window_bytes=256):
    """Locate the movie-encoder height word in RAM by signature scan.

    Walks the mapped libmpr region in chunks (with a small overlap window) and
    looks for the ARM64 'movz <reg>, #0x870' (height 2160) instruction that sits
    within `window_bytes` of a 'movz <reg>, #0xf00' (width 3840) store - the
    geometry pair the encoder loads together. Returns the address of the height
    word, or None if not found.

    No proprietary Sony firmware bytes are embedded: only the public ARM64 MOVZ
    opcode encoding and the two plain integers 2160 and 3840 are used. The scan
    range (the libmpr mapped base + size) must be supplied once resolved on
    hardware; without it the function refuses rather than guess."""
    if scan_start is None or scan_size is None:
        raise MscError(
            "scan range required: pass --scan-start and --scan-size (the libmpr "
            "mapped base and length, resolved from the loader map on hardware).")

    addr = scan_start
    end = scan_start + scan_size
    tail = b""
    tail_addr = scan_start
    while addr < end:
        n = min(chunk, end - addr)
        buf = dev.mem_read(addr, n)          # read-only
        region = tail + bytes(buf)
        base = tail_addr
        limit = len(region) - 3
        for off in range(0, limit, 4):
            word = int.from_bytes(region[off:off + 4], "little")
            if not _is_movz_imm(word, STOCK_HEIGHT):
                continue
            lo = max(0, off - window_bytes)
            hi = min(limit, off + window_bytes)
            for o2 in range(lo, hi, 4):
                w2 = int.from_bytes(region[o2:o2 + 4], "little")
                if _is_movz_imm(w2, OPENGATE_WIDTH):
                    return base + off
        keep = min(window_bytes, len(region)) & ~0x3   # stay 4-byte aligned
        tail = region[len(region) - keep:] if keep else b""
        tail_addr = base + len(region) - keep
        addr += n
    return None


def probe_msc(dev):
    """Read-only SCSI BOT probe: INQUIRY + TEST UNIT READY + READ CAPACITY(10)."""
    print("[probe ] standard SCSI Bulk-Only Transport probe (read-only)...")
    st, data = dev.inquiry()
    if st == 0 and len(data) >= 36:
        vendor = data[8:16].decode("ascii", "replace").strip()
        product = data[16:32].decode("ascii", "replace").strip()
        rev = data[32:36].decode("ascii", "replace").strip()
        pdt = data[0] & 0x1F
        print(f"[probe ] INQUIRY ok: vendor={vendor!r} product={product!r} "
              f"rev={rev!r} device-type=0x{pdt:02X}")
    else:
        print(f"[probe ] INQUIRY no/!=0 status ({st}); BOT framing may differ.")

    st2, _ = dev.test_unit_ready()
    print("[probe ] TEST UNIT READY -> "
          + ("ready (status 0)" if st2 == 0
             else f"status {st2} (not ready / no medium - normal for a camera)"))

    st3, cap = dev.read_capacity10()
    if st3 == 0 and len(cap) >= 8:
        last_lba, blk = struct.unpack(">II", cap[:8])
        total = (last_lba + 1) * blk
        print(f"[probe ] READ CAPACITY: {last_lba + 1} blocks x {blk} B "
              f"(~{total / (1024 ** 2):.1f} MiB logical).")
    else:
        print(f"[probe ] READ CAPACITY no/!=0 status ({st3}).")

    responded = (st is not None) or (st2 is not None) or (st3 is not None)
    print("[probe ] result: standard SCSI BOT framing "
          + ("RESPONDS on this BIONZ XR body." if responded
             else "did NOT respond (unexpected)."))
    print("[probe ] (no vendor memory CDB was sent; configure those separately.)")
    return responded


def main():
    ap = argparse.ArgumentParser(
        description="Volatile RAM Open Gate research helper (A6700). PTP aspect "
                    "ratio is blocked by the HAITA app layer; this targets the "
                    "downstream encoder height word in RAM only.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true", default=True,
                      help="(default) read-only: locate + verify stock bytes, write nothing.")
    mode.add_argument("--probe-msc", action="store_true",
                      help="read-only: send safe INQUIRY/TEST UNIT READY/READ CAPACITY "
                           "and report whether SCSI BOT framing responds.")
    mode.add_argument("--confirm-ram-write", action="store_true",
                      help="opt-in: apply the volatile RAM patch (gone at power-off).")
    mode.add_argument("--restore", action="store_true",
                      help="write the stock/backed-up bytes back (no reboot).")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=A6700_MSC_PID)
    ap.add_argument("--scan-start", type=lambda x: int(x, 0), default=None,
                    help="libmpr mapped base address for the signature scan.")
    ap.add_argument("--scan-size", type=lambda x: int(x, 0), default=None,
                    help="length in bytes to scan from --scan-start.")
    args = ap.parse_args()

    writing = args.confirm_ram_write or args.restore
    if args.probe_msc:
        head = "MSC PROBE (read-only)"
    elif writing:
        head = "RAM WRITE"
    else:
        head = "VERIFY-ONLY (read)"
    print(f"=== ram_opengate: {head} ===")

    try:
        dev = MscDevice.open(pid=args.pid)
    except (MscError, usb.core.USBError) as e:
        sys.exit(f"[ERROR] {e}")

    try:
        if args.probe_msc:
            probe_msc(dev)
            return

        site = find_libmpr_height_site(dev, args.scan_start, args.scan_size)
        if site is None:
            sys.exit("[ERROR] height/width signature not found in the scan range.")
        cur = struct.unpack("<H", dev.mem_read(site, 2))[0]
        label = ("stock 2160" if cur == STOCK_HEIGHT else
                 "patched 2560" if cur == OPENGATE_HEIGHT else "?")
        print(f"[+] height word @0x{site:x} = 0x{cur:04X} ({label})")

        if args.restore:
            dev.mem_write(site, struct.pack("<H", STOCK_HEIGHT))
            print("[+] restored stock 0x0870 (2160).")
        elif args.confirm_ram_write:
            print(f"[backup] 0x{site:x} = 0x{cur:04X}")   # pre-patch backup
            dev.mem_write(site, struct.pack("<H", OPENGATE_HEIGHT))
            chk = struct.unpack("<H", dev.mem_read(site, 2))[0]   # readback verify
            print(f"[+] wrote 0x0A00 (2560); readback 0x{chk:04X} "
                  + ("OK (volatile, gone at power-off)" if chk == OPENGATE_HEIGHT
                     else "MISMATCH - consider --restore"))
        else:
            ok = (cur == STOCK_HEIGHT)
            print("[verify] " + ("OK: stock bytes present, nothing written."
                                  if ok else "unexpected value; no write (read-only)."))
    except MscError as e:
        sys.exit(f"[ERROR] {e}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
