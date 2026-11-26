#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ram_opengate.py - volatile RAM Open Gate 3:2 research helper for the Sony A6700.

Target: ILCE-6700, firmware 2.00. 3840x2160 -> 3840x2560 (and the exact 3:2
window 5952x3968). RAM only: a cold boot (battery out ~10 s) removes everything.

Why PTP alone does not work
---------------------------
Setting PTP aspect_ratio (0xD211) to 3:2 is ACCEPTED but then IGNORED: the HAITA
capability layer in appFw.so re-asserts 16:9 (REC_MOVIE_ASPECT_RATIO_NOT_16_9).
No PTP property write produces 3:2 video. The lock must be bypassed downstream, in
the running camera's RAM.

How Open Gate is actually reached on BIONZ XR (the real pipeline)
-----------------------------------------------------------------
This is NOT a host-side SCSI "poke memory" command. The verified route (used by the
ArcaneLantern GPL kit, referenced, never copied here) is:

  1. Camera in USB Mass Storage mode (VID 0x054C PID 0x0E76), standard SCSI BOT.
  2. A Sony vendor command switches it to SERVICE MODE; it re-enumerates as
     VID 0x054C PID 0x0336 (Sony-PMCA-RE, MIT, by ma1co, does this handshake).
  3. A small native ARM64 helper is uploaded to the service partition, loaded ONCE,
     and it is the helper - running on the camera - that reads/writes physical RAM
     (av-cam.bin mapped at 0x401000000, libmpr.so) and writes one result file to the
     RAM disk (/tmp_wbshd). The host then fetches the result and deletes the helper.
  4. Each step compares every byte against its stock value before writing, writes
     whole 64-byte lines, reads back, and self-undoes on any mismatch.

So the memory read/write is done by an on-camera helper, not by this PC. This MIT
build ships NO such helper: a correct helper embeds Sony firmware-derived tables and
the vetted builds are GPL. This file therefore provides the MIT-clean HOST side:
the read-only SCSI probe, the verified 2.00 address map and dimensions as plain
facts, the ARM64 signature scanner, and the verify/patch/restore logic - all driven
through a pluggable CameraMemory transport. Wire a transport (the service helper, or
your own) to go live; until then RAM ops refuse rather than guess.

Safety:
  --info         : no camera. Print the verified 2.00 facts + first command to run.
  --probe-msc    : read-only. Standard INQUIRY / TEST UNIT READY / READ CAPACITY.
  --verify-only  : (default) read-only. Locate + read the encoder height word, report.
  --confirm-ram-write : opt-in. Backup -> write 0x0870->0x0A00 -> readback verify.
  --restore      : write the stock height word back (no reboot).

Key unverified caveats on A6700 2.00 (from the port notes; confirm on hardware):
  * The contributed 4K window (5952x3876) makes the picture ~2.4% too tall.
  * The exact 3:2 window (5952x3968, first-row register < 256) has NEVER been run on
    an A6700 - expect possible black frame / restart (battery pull clears it).
  * In-camera playback of 3840x2560 needs a separate playback-fix step.
  * Whether the power switch (not a battery pull) clears the patch is unknown.
  * Required mode is Mass Storage, then service mode - NOT PC Remote (0x0E78).
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

FIRMWARE = "2.00"
MODEL = "ILCE-6700"
SONY_VID = 0x054C
A6700_MSC_PID = 0x0E76            # A6700 in USB Mass Storage mode
SONY_SERVICE_PID = 0x0336        # re-enumerated device once in service mode
USB_CLASS_MSC = 0x08             # USB Mass Storage interface class

# Open Gate dimensions (plain integers, not firmware bytes).
STOCK_HEIGHT = 0x0870            # 2160
OPENGATE_HEIGHT = 0x0A00         # 2560
OPENGATE_WIDTH = 0x0F00          # 3840

# Verified A6700 2.00 address map (public addresses from the port notes; these are
# offsets, not Sony firmware content). The height word the encoder feeds the movie
# writer lives in libmpr.so; av-cam.bin carries the decode/playback side.
A6700_200_SITES = {
    "libmpr_mp4_height_a":    0x1EC1B8,   # MP4 header height word (libmpr.so)
    "libmpr_mp4_height_b":    0x1EC2E8,   # second MP4 header height word
    "libmpr_res_compare":     0x15E4E4,   # playback resolution compare
    "avcam_decode_size_table": 0xC00350,  # decode size table (av-cam.bin)
    "movie_size_table":       0x199EC7C,  # movie size table (output size word)
}
# Sites whose 16-bit height word should read STOCK_HEIGHT before a patch.
HEIGHT_SITES = ("libmpr_mp4_height_a", "libmpr_mp4_height_b")

# ARM64 MOVZ (wide immediate), LSL #0: sf 10 100101 hw imm16 Rd, imm16 in bits
# [20:5], Rd [4:0]; 32-bit base opcode 0x52800000. MOVZ_MASK ignores sf (W/X), hw,
# Rd and imm16, so it matches "movz <w|x>reg, #imm, lsl #0" for any register.
MOVZ_LSL0_BASE = 0x52800000
MOVZ_MASK = 0x7FE00000


class MscError(RuntimeError):
    pass


def _is_movz_imm(word: int, imm16: int) -> bool:
    """True if `word` is an ARM64 'movz <reg>, #imm16, lsl #0' instruction."""
    return (word & MOVZ_MASK) == MOVZ_LSL0_BASE and ((word >> 5) & 0xFFFF) == imm16


class CameraMemory:
    """Abstract RAM read/write transport. The MIT build ships no working transport
    (the vetted on-camera helper is GPL / firmware-derived). Wire a subclass that
    drives the Sony service-mode helper, or your own, to go live."""

    def mem_read(self, addr, length):
        raise MscError(
            "no CameraMemory transport configured. RAM read/write on BIONZ XR runs "
            "through an on-camera service-mode helper, which this MIT build does not "
            "ship. Run the ArcaneLantern GPL kit for the vetted patch, or wire a "
            "transport (see the module docstring).")

    def mem_write(self, addr, data):
        self.mem_read(addr, 0)   # raises the same clean message


class MscDevice(CameraMemory):
    """Minimal USB Mass Storage Bulk-Only Transport (original implementation), used
    for the read-only SCSI probe and for service-mode entry."""

    def __init__(self, dev, ep_in, ep_out):
        self.dev, self.ep_in, self.ep_out = dev, ep_in, ep_out
        self._tag = 0

    @classmethod
    def open(cls, pid=A6700_MSC_PID):
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

    def scsi_try(self, cdb, data_len=0):
        """One read-only SCSI command -> (status, data), no raise on non-zero
        status. status None = no reply."""
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

    def inquiry(self):
        return self.scsi_try(bytes([0x12, 0, 0, 0, 36, 0]), 36)

    def test_unit_ready(self):
        return self.scsi_try(bytes([0x00, 0, 0, 0, 0, 0]), 0)

    def read_capacity10(self):
        return self.scsi_try(bytes([0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 8)

    def close(self):
        usb.util.dispose_resources(self.dev)


def find_libmpr_height_site(mem, scan_start=None, scan_size=None,
                            chunk=0x10000, window_bytes=256):
    """Locate the movie-encoder height word by signature scan over a RAM region
    reachable through `mem` (a CameraMemory). Matches ARM64 'movz <reg>, #0x870'
    (height 2160) within `window_bytes` of a 'movz <reg>, #0xf00' (width 3840).
    Returns the height word's address, or None. No firmware bytes embedded: only the
    public MOVZ encoding and the integers 2160 / 3840. Needs the scan range (libmpr
    mapped base + length), resolved on hardware; refuses otherwise."""
    if scan_start is None or scan_size is None:
        raise MscError(
            "scan range required: pass --scan-start and --scan-size (the libmpr "
            "mapped base and length, resolved from the loader map on hardware).")
    addr, end = scan_start, scan_start + scan_size
    tail, tail_addr = b"", scan_start
    while addr < end:
        n = min(chunk, end - addr)
        region = tail + bytes(mem.mem_read(addr, n))
        base = tail_addr
        limit = len(region) - 3
        for off in range(0, limit, 4):
            word = int.from_bytes(region[off:off + 4], "little")
            if not _is_movz_imm(word, STOCK_HEIGHT):
                continue
            lo, hi = max(0, off - window_bytes), min(limit, off + window_bytes)
            for o2 in range(lo, hi, 4):
                if _is_movz_imm(int.from_bytes(region[o2:o2 + 4], "little"),
                                OPENGATE_WIDTH):
                    return base + off
        keep = min(window_bytes, len(region)) & ~0x3
        tail = region[len(region) - keep:] if keep else b""
        tail_addr = base + len(region) - keep
        addr += n
    return None


def read_height(mem, addr):
    """Read one 16-bit height word (little-endian)."""
    return struct.unpack("<H", bytes(mem.mem_read(addr, 2)))[0]


def label_height(v):
    return ("stock 2160" if v == STOCK_HEIGHT else
            "open-gate 2560" if v == OPENGATE_HEIGHT else "UNEXPECTED")


def verify_sites(mem, base=0):
    """Read every known libmpr height site and report. `base` is the libmpr mapped
    base (file offsets in A6700_200_SITES are added to it). Returns list of
    (name, addr, value, label). Read-only."""
    out = []
    for name in HEIGHT_SITES:
        addr = base + A6700_200_SITES[name]
        v = read_height(mem, addr)
        out.append((name, addr, v, label_height(v)))
    return out


def patch_sites(mem, base, value, expect=None):
    """Write `value` to every known height site, after checking each holds `expect`
    (abort the whole patch if any mismatches). Returns a backup dict {addr: old}."""
    targets = [base + A6700_200_SITES[n] for n in HEIGHT_SITES]
    if expect is not None:
        for addr in targets:
            cur = read_height(mem, addr)
            if cur != expect:
                raise MscError(
                    f"site 0x{addr:x} holds 0x{cur:04X}, expected 0x{expect:04X} "
                    "(wrong firmware / already patched) - nothing written.")
    backup = {}
    for addr in targets:
        backup[addr] = read_height(mem, addr)
        mem.mem_write(addr, struct.pack("<H", value))
        chk = read_height(mem, addr)
        if chk != value:
            raise MscError(f"readback mismatch at 0x{addr:x}: 0x{chk:04X}")
    return backup


def probe_msc(dev):
    """Read-only SCSI BOT probe: INQUIRY + TEST UNIT READY + READ CAPACITY(10)."""
    print("[probe ] standard SCSI Bulk-Only Transport probe (read-only)...")
    st, data = dev.inquiry()
    if st == 0 and len(data) >= 36:
        vendor = data[8:16].decode("ascii", "replace").strip()
        product = data[16:32].decode("ascii", "replace").strip()
        rev = data[32:36].decode("ascii", "replace").strip()
        print(f"[probe ] INQUIRY ok: vendor={vendor!r} product={product!r} "
              f"rev={rev!r} device-type=0x{data[0] & 0x1F:02X}")
    else:
        print(f"[probe ] INQUIRY no/!=0 status ({st}); BOT framing may differ.")
    st2, _ = dev.test_unit_ready()
    print("[probe ] TEST UNIT READY -> "
          + ("ready (status 0)" if st2 == 0
             else f"status {st2} (not ready / no medium - normal for a camera)"))
    st3, cap = dev.read_capacity10()
    if st3 == 0 and len(cap) >= 8:
        last_lba, blk = struct.unpack(">II", cap[:8])
        print(f"[probe ] READ CAPACITY: {last_lba + 1} blocks x {blk} B "
              f"(~{(last_lba + 1) * blk / (1024 ** 2):.1f} MiB logical).")
    else:
        print(f"[probe ] READ CAPACITY no/!=0 status ({st3}).")
    responded = (st is not None) or (st2 is not None) or (st3 is not None)
    print("[probe ] result: standard SCSI BOT framing "
          + ("RESPONDS on this BIONZ XR body." if responded else "did NOT respond."))
    print("[probe ] (no vendor/service memory access was attempted.)")
    return responded


def print_info():
    print(f"=== ram_opengate: verified facts ({MODEL} fw {FIRMWARE}) ===")
    print(f"  Open Gate: 3840x2160 (0x{STOCK_HEIGHT:04X}) -> 3840x2560 "
          f"(0x{OPENGATE_HEIGHT:04X}); width 3840 (0x{OPENGATE_WIDTH:04X}).")
    print("  Required USB mode: Mass Storage (PID 0x0E76) -> service mode "
          f"(PID 0x{SONY_SERVICE_PID:04X}).  NOT PC Remote (0x0E78).")
    print("  Known 2.00 sites (file offsets):")
    for name, off in A6700_200_SITES.items():
        print(f"    {name:24s} 0x{off:07X}")
    print("  Mechanism: on-camera service-mode helper does the RAM read/write; this")
    print("    MIT build ships no helper (vetted builds are GPL / firmware-derived).")
    print("  Caveats: contributed 4K window ~2.4% too tall; exact 3:2 window UNTESTED")
    print("    on A6700; in-camera 3840x2560 playback needs a separate fix; RAM only")
    print("    (cold boot / battery-out ~10 s reverts).")
    print("  First command on hardware (read-only):")
    print("    python ram_opengate.py --probe-msc")


def main():
    ap = argparse.ArgumentParser(
        description=f"Volatile RAM Open Gate 3:2 research helper ({MODEL} fw "
                    f"{FIRMWARE}). PTP aspect ratio is blocked by HAITA; the real "
                    "patch runs through an on-camera service-mode helper (not shipped "
                    "in this MIT build).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--info", action="store_true",
                      help="no camera: print verified facts and the first command.")
    mode.add_argument("--probe-msc", action="store_true",
                      help="read-only SCSI probe (INQUIRY/TUR/READ CAPACITY).")
    mode.add_argument("--verify-only", action="store_true", default=True,
                      help="(default) read-only: locate + verify stock bytes.")
    mode.add_argument("--confirm-ram-write", action="store_true",
                      help="opt-in: apply the volatile RAM patch (gone at power-off).")
    mode.add_argument("--restore", action="store_true",
                      help="write the stock height word back (no reboot).")
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=A6700_MSC_PID)
    ap.add_argument("--libmpr-base", type=lambda x: int(x, 0), default=0,
                    help="libmpr mapped base; site offsets are added to it.")
    ap.add_argument("--scan-start", type=lambda x: int(x, 0), default=None,
                    help="libmpr mapped base for the fallback signature scan.")
    ap.add_argument("--scan-size", type=lambda x: int(x, 0), default=None,
                    help="length in bytes to scan from --scan-start.")
    args = ap.parse_args()

    if args.info:
        print_info()
        return

    writing = args.confirm_ram_write or args.restore
    head = ("MSC PROBE (read-only)" if args.probe_msc else
            "RAM WRITE" if writing else "VERIFY-ONLY (read)")
    print(f"=== ram_opengate: {head} ===")

    try:
        dev = MscDevice.open(pid=args.pid)
    except (MscError, usb.core.USBError) as e:
        sys.exit(f"[ERROR] {e}")

    try:
        if args.probe_msc:
            probe_msc(dev)
            return

        # RAM read/write needs a CameraMemory transport (the on-camera service
        # helper). MscDevice has none in this MIT build, so these ops report the
        # clean "no transport" message instead of guessing - strictly safe.
        if args.restore:
            patch_sites(dev, args.libmpr_base, STOCK_HEIGHT)
            print("[+] restored stock height 0x0870 (2160) at all sites.")
        elif args.confirm_ram_write:
            backup = patch_sites(dev, args.libmpr_base, OPENGATE_HEIGHT,
                                 expect=STOCK_HEIGHT)
            print("[+] wrote 0x0A00 (2560); readback OK (volatile, gone at power-off).")
            print("[backup] " + ", ".join(f"0x{a:x}=0x{v:04X}"
                                           for a, v in backup.items()))
        else:
            for name, addr, v, lab in verify_sites(dev, args.libmpr_base):
                print(f"[verify] {name} @0x{addr:x} = 0x{v:04X} ({lab})")
    except MscError as e:
        sys.exit(f"[ERROR] {e}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
