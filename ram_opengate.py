#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ram_opengate.py - volatile RAM Open Gate helper for the Sony A6700 (RESEARCH).

Channel: USB Mass Storage (SCSI Bulk-Only Transport) vendor commands - the
open-source Sony updater / PMCA-RE style service transport (A6700 Mass Storage
PID 0x0E76). This file is ORIGINAL code (MIT): it reimplements the generic
USB-MSC BOT framing and leaves the Sony vendor memory CDBs as clearly-marked
constants to confirm on hardware. It contains NO firmware bytes and NO GPL code.

Safety:
  --verify-only (default): STRICTLY read-only. Finds libmpr.so in memory and
    checks the expected stock bytes (3840x2160 height #0x870) - writes nothing.
  --confirm-ram-write: opt-in. Backs up the original RAM bytes, applies the
    volatile patch (#0x870 -> #0xa00), gone on power-off / battery pull.
  --restore: writes the backed-up / stock bytes back, no reboot.

Open Gate is blocked at the app layer (HAITA); this targets the downstream
encoder height word, in RAM only. Research tool - not guaranteed to run until
the vendor memory CDBs are filled in from the open updater protocol.
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
USB_CLASS_MSC = 0x08

# Stock encoder height word (little-endian movz #0x870 = 2160) and the Open Gate
# value (#0xa00 = 2560). The exact RAM site is resolved by signature, not stored.
STOCK_HEIGHT = 0x0870
OPENGATE_HEIGHT = 0x0A00

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


class MscDevice:
    """Minimal USB Mass Storage Bulk-Only Transport (original implementation)."""

    def __init__(self, dev, ep_in, ep_out):
        self.dev, self.ep_in, self.ep_out = dev, ep_in, ep_out
        self._tag = 0

    @classmethod
    def open(cls, pid=A6700_MSC_PID):
        dev = usb.core.find(idVendor=SONY_VID, idProduct=pid)
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


def find_libmpr_height_site(dev):
    """Locate libmpr.so in RAM and return the address of the encoder height word.
    Uses mem_read + a signature scan for the movz #0x870 site (no firmware bytes
    embedded). Returns address or None."""
    # Research stub: the scan walks the mapped libmpr region and matches the
    # movz-w,#0x870 encoding near the 3840 (#0xf00) width store. Requires
    # mem_read to be live (vendor CDB configured).
    raise MscError("memory scan requires the vendor CDBs to be configured; "
                   "this is the research hook, not yet live on hardware.")


def main():
    ap = argparse.ArgumentParser(description="Volatile RAM Open Gate helper (A6700).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true", default=True,
                      help="(default) read-only: verify stock bytes, write nothing.")
    mode.add_argument("--confirm-ram-write", action="store_true",
                      help="opt-in: apply the volatile RAM patch (gone at power-off).")
    mode.add_argument("--restore", action="store_true",
                      help="write the stock/backed-up bytes back (no reboot).")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=A6700_MSC_PID)
    args = ap.parse_args()

    writing = args.confirm_ram_write or args.restore
    print("=== ram_opengate: " + ("RAM WRITE" if writing else "VERIFY-ONLY (read)")
          + " ===")
    try:
        dev = MscDevice.open(pid=args.pid)
    except (MscError, usb.core.USBError) as e:
        sys.exit(f"[ERROR] {e}")

    backup = {}
    try:
        site = find_libmpr_height_site(dev)
        cur = struct.unpack("<H", dev.mem_read(site, 2))[0]
        print(f"[+] height word @0x{site:x} = 0x{cur:04X} "
              f"({'stock 2160' if cur == STOCK_HEIGHT else 'patched 2560' if cur == OPENGATE_HEIGHT else '?'})")

        if args.restore:
            dev.mem_write(site, struct.pack("<H", STOCK_HEIGHT))
            print("[+] restored stock 0x0870 (2160).")
        elif args.confirm_ram_write:
            backup[site] = cur
            print(f"[backup] 0x{site:x} = 0x{cur:04X}")
            dev.mem_write(site, struct.pack("<H", OPENGATE_HEIGHT))
            chk = struct.unpack("<H", dev.mem_read(site, 2))[0]
            print(f"[+] wrote 0x0A00 (2560); readback 0x{chk:04X} "
                  + ("OK (volatile, gone at power-off)" if chk == OPENGATE_HEIGHT
                     else "MISMATCH"))
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
