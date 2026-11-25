#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_a6700.py — Sonde de diagnostic USB *en lecture seule* pour Sony A6700 (ILCE-6700).

Objectif
--------
Établir un dialogue PTP/USB avec le boîtier et lire des informations non
destructives :
    1. OpenSession            (opcode PTP standard 0x1002)
    2. GetDeviceInfo          (opcode PTP standard 0x1001)   [lecture]
    3. SDIO Connect           (opcode vendor Sony  0x9201)   [handshake de session]
    4. GetExtDeviceInfo       (opcode vendor Sony  0x9202)   [lecture capacités]
    5. GetExtDevicePropDesc   (opcode vendor Sony  0x9203)   [lecture descripteurs]

GARANTIE DE SÉCURITÉ
--------------------
Ce script est STRICTEMENT en lecture seule. Il n'émet AUCUNE opération
d'écriture, de déclenchement ou de contrôle :
    - pas de SetExtDevicePropValue (0x9205)
    - pas de ControlDevice        (0x9207)  -> jamais de S1/S2/Movie Rec
    - pas de SendObject / suppression / formatage / mise à jour firmware
Toutes les opérations émises sont validées contre une liste blanche
(`READ_ONLY_OPS`). Toute tentative d'émettre un autre opcode lève une
exception avant même l'envoi au boîtier.

Ce dépôt ne contient aucun fichier issu du firmware Sony : les codes PTP
utilisés ici sont des constantes de protocole publiques (PTP/ISO 15740) et
l'espace vendor Sony « SDIO », documentés de façon indépendante.

Dépendances : pyusb (+ libusb-1.0 / pilote WinUSB via Zadig sous Windows).
Voir README.md.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover
    sys.exit("[ERREUR] pyusb manquant. Installez-le : pip install pyusb")

# ---------------------------------------------------------------------------
# Constantes de protocole
# ---------------------------------------------------------------------------

SONY_VID = 0x054C  # Sony Corporation (identifiant constructeur USB)

# Classe d'interface USB « Still Image / PTP »
USB_CLASS_STILL_IMAGE = 0x06

# Types de conteneur PTP/USB
PTP_CONTAINER_COMMAND = 0x0001
PTP_CONTAINER_DATA = 0x0002
PTP_CONTAINER_RESPONSE = 0x0003
PTP_CONTAINER_EVENT = 0x0004

# Opcodes autorisés (LECTURE SEULE). Toute opération hors de cet ensemble
# est refusée par transaction().
OP_OPEN_SESSION = 0x1002
OP_CLOSE_SESSION = 0x1003
OP_GET_DEVICE_INFO = 0x1001
OP_SDIO_CONNECT = 0x9201
OP_SDIO_GET_EXT_DEVICE_INFO = 0x9202
OP_SDIO_GET_EXT_DEVICE_PROP_DESC = 0x9203

READ_ONLY_OPS = {
    OP_OPEN_SESSION,
    OP_CLOSE_SESSION,
    OP_GET_DEVICE_INFO,
    OP_SDIO_CONNECT,
    OP_SDIO_GET_EXT_DEVICE_INFO,
    OP_SDIO_GET_EXT_DEVICE_PROP_DESC,
}

OP_NAMES = {
    OP_OPEN_SESSION: "OpenSession",
    OP_CLOSE_SESSION: "CloseSession",
    OP_GET_DEVICE_INFO: "GetDeviceInfo",
    OP_SDIO_CONNECT: "SDIO_Connect",
    OP_SDIO_GET_EXT_DEVICE_INFO: "SDIO_GetExtDeviceInfo",
    OP_SDIO_GET_EXT_DEVICE_PROP_DESC: "SDIO_GetExtDevicePropDesc",
}

PTP_RC_OK = 0x2001  # Response code « OK »

# Quelques noms symboliques de DevicePropCode utiles à l'affichage
# (constantes de protocole uniquement ; aucune donnée de firmware).
PROP_NAMES = {
    0x5013: "still_capture_mode (drive mode)",
    0xD211: "aspect_ratio",
    0xD241: "file_format_movie",
    0xD242: "recording_setting_movie",
    0xD21E: "iso_sensitivity",
    0xD20D: "shutter_speed",
}

DEFAULT_TIMEOUT_MS = 4000


# ---------------------------------------------------------------------------
# Couche conteneur PTP/USB
# ---------------------------------------------------------------------------

class PtpError(RuntimeError):
    pass


class PtpUsbDevice:
    """Transport PTP minimal au-dessus de pyusb (bulk-in / bulk-out)."""

    def __init__(self, dev: "usb.core.Device", intf, ep_in, ep_out):
        self.dev = dev
        self.intf = intf
        self.ep_in = ep_in
        self.ep_out = ep_out
        self._txid = 0

    # -- découverte -------------------------------------------------------

    @classmethod
    def open_first(cls, vid: int = SONY_VID, pid: int | None = None) -> "PtpUsbDevice":
        kwargs = {"idVendor": vid, "find_all": True}
        if pid is not None:
            kwargs["idProduct"] = pid
        candidates = list(usb.core.find(**kwargs))
        if not candidates:
            raise PtpError(
                f"Aucun périphérique USB Sony (VID 0x{vid:04X}) trouvé. "
                "Le boîtier est-il allumé, en mode « PC Remote » et relié en USB ?"
            )

        for dev in candidates:
            intf = cls._find_ptp_interface(dev)
            if intf is None:
                continue
            ep_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: (
                    usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT
                    and usb.util.endpoint_type(e.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
                ),
            )
            ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: (
                    usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_IN
                    and usb.util.endpoint_type(e.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
                ),
            )
            if ep_in is None or ep_out is None:
                continue

            # Sous Windows, il n'y a pas de pilote noyau à détacher (WinUSB).
            try:
                if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
            except (NotImplementedError, usb.core.USBError):
                pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                # Déjà configuré : on continue.
                pass
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
            return cls(dev, intf, ep_in, ep_out)

        raise PtpError(
            "Périphérique Sony trouvé mais aucune interface PTP (classe 0x06) "
            "exploitable. Vérifiez le mode de connexion USB du boîtier "
            "(PC Remote / PTP) et le pilote WinUSB (Zadig)."
        )

    @staticmethod
    def _find_ptp_interface(dev):
        try:
            for cfg in dev:
                for intf in cfg:
                    if intf.bInterfaceClass == USB_CLASS_STILL_IMAGE:
                        return intf
        except usb.core.USBError:
            return None
        return None

    def close(self):
        try:
            usb.util.release_interface(self.dev, self.intf.bInterfaceNumber)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)

    # -- transaction ------------------------------------------------------

    def _next_txid(self) -> int:
        self._txid = (self._txid + 1) & 0xFFFFFFFF
        return self._txid

    def transaction(self, opcode: int, params=(), timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """Émet une opération PTP (phase commande, phase données en RÉCEPTION
        uniquement, phase réponse) et renvoie (response_code, data_bytes).

        Refuse tout opcode absent de la liste blanche READ_ONLY_OPS.
        Ne réalise JAMAIS de phase de données en émission (aucune écriture).
        """
        if opcode not in READ_ONLY_OPS:
            raise PtpError(
                f"REFUS : opcode 0x{opcode:04X} hors liste blanche lecture seule. "
                "Ce script n'émet aucune opération d'écriture/contrôle."
            )

        params = list(params)
        if len(params) > 5:
            raise PtpError("PTP : au plus 5 paramètres par opération.")

        txid = self._next_txid()

        # --- Phase commande ---
        body = struct.pack("<HHI", PTP_CONTAINER_COMMAND, opcode, txid)
        body += b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params)
        packet = struct.pack("<I", len(body) + 4) + body
        self.ep_out.write(packet, timeout_ms)

        # --- Phase données (réception éventuelle) ---
        data = b""
        first = self._read_container(timeout_ms)
        ctype = first["type"]
        if ctype == PTP_CONTAINER_DATA:
            data = first["payload"]
            resp = self._read_container(timeout_ms)
        elif ctype == PTP_CONTAINER_RESPONSE:
            resp = first
        else:
            raise PtpError(f"Conteneur inattendu type=0x{ctype:04X}")

        if resp["type"] != PTP_CONTAINER_RESPONSE:
            raise PtpError(f"Réponse PTP absente (type=0x{resp['type']:04X})")

        return resp["code"], data

    def _read_container(self, timeout_ms: int):
        raw = bytes(self.ep_in.read(self.ep_in.wMaxPacketSize * 8, timeout_ms))
        if len(raw) < 12:
            raise PtpError("Conteneur PTP tronqué (en-tête incomplet).")
        length, ctype, code, txid = struct.unpack_from("<IHHI", raw, 0)
        payload = raw[12:length]
        # Récupère le reste des données si le message dépasse un transfert.
        while len(raw) < length:
            chunk = bytes(self.ep_in.read(self.ep_in.wMaxPacketSize * 8, timeout_ms))
            if not chunk:
                break
            raw += chunk
            payload = raw[12:length]
        return {"length": length, "type": ctype, "code": code,
                "txid": txid, "payload": payload}


# ---------------------------------------------------------------------------
# Décodage minimal des jeux de données PTP
# ---------------------------------------------------------------------------

def _read_ptp_string(buf: bytes, off: int):
    """Chaîne PTP : 1 octet (nb de caractères) + UTF-16LE."""
    if off >= len(buf):
        return "", off
    n = buf[off]
    off += 1
    if n == 0:
        return "", off
    raw = buf[off:off + (n * 2)]
    off += n * 2
    s = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return s, off


def _read_uint16_array(buf: bytes, off: int):
    (count,) = struct.unpack_from("<I", buf, off)
    off += 4
    vals = list(struct.unpack_from("<%dH" % count, buf, off))
    off += count * 2
    return vals, off


def parse_device_info(data: bytes) -> dict:
    """Décode les champs utiles du dataset DeviceInfo (GetDeviceInfo)."""
    info = {}
    try:
        off = 0
        std_ver, vendor_ext_id, vendor_ext_ver = struct.unpack_from("<HIH", data, off)
        off += 8
        info["standard_version"] = std_ver
        info["vendor_extension_id"] = vendor_ext_id
        info["vendor_extension_version"] = vendor_ext_ver
        info["vendor_extension_desc"], off = _read_ptp_string(data, off)
        # functional mode (uint16)
        off += 2
        info["operations_supported"], off = _read_uint16_array(data, off)
        info["events_supported"], off = _read_uint16_array(data, off)
        info["device_properties_supported"], off = _read_uint16_array(data, off)
        info["capture_formats"], off = _read_uint16_array(data, off)
        info["image_formats"], off = _read_uint16_array(data, off)
        info["manufacturer"], off = _read_ptp_string(data, off)
        info["model"], off = _read_ptp_string(data, off)
        info["device_version"], off = _read_ptp_string(data, off)
        info["serial_number"], off = _read_ptp_string(data, off)
    except (struct.error, IndexError):
        info["_parse_warning"] = "dataset DeviceInfo tronqué / non standard"
    return info


# ---------------------------------------------------------------------------
# Séquence de diagnostic
# ---------------------------------------------------------------------------

def rc_str(rc: int) -> str:
    return "OK" if rc == PTP_RC_OK else f"0x{rc:04X}"


def run_probe(pid: int | None, do_sdio: bool = True):
    print("=== probe_a6700 : diagnostic USB LECTURE SEULE ===\n")
    dev = PtpUsbDevice.open_first(pid=pid)
    print(f"[+] Périphérique PTP ouvert "
          f"(VID 0x{dev.dev.idVendor:04X} PID 0x{dev.dev.idProduct:04X}, "
          f"interface #{dev.intf.bInterfaceNumber}).\n")

    try:
        # 1) OpenSession
        rc, _ = dev.transaction(OP_OPEN_SESSION, params=[1])
        print(f"[1] OpenSession(0x1002)          -> {rc_str(rc)}")
        if rc != PTP_RC_OK:
            print("    (session non ouverte, arrêt.)")
            return

        # 2) GetDeviceInfo (lecture)
        rc, data = dev.transaction(OP_GET_DEVICE_INFO)
        print(f"[2] GetDeviceInfo(0x1001)        -> {rc_str(rc)} ({len(data)} octets)")
        if rc == PTP_RC_OK and data:
            di = parse_device_info(data)
            print(f"      Fabricant        : {di.get('manufacturer','?')}")
            print(f"      Modèle           : {di.get('model','?')}")
            print(f"      Version firmware : {di.get('device_version','?')}")
            print(f"      N° de série      : {di.get('serial_number','?')}")
            print(f"      Ext. vendor      : id=0x{di.get('vendor_extension_id',0):X}"
                  f" « {di.get('vendor_extension_desc','')} »")
            ops = di.get("operations_supported", [])
            props = di.get("device_properties_supported", [])
            print(f"      Opérations       : {len(ops)} "
                  f"(dont vendor 0x92xx : {sum(1 for o in ops if 0x9200 <= o <= 0x92FF)})")
            print(f"      Propriétés       : {len(props)}")

        if not do_sdio:
            return

        # 3) SDIO Connect — handshake de session étendue (lecture/négociation)
        #    Séquence de négociation en 2 phases ; aucun réglage boîtier modifié.
        for phase in (1, 2):
            rc, _ = dev.transaction(OP_SDIO_CONNECT, params=[phase, 0x0000DA01, 0])
            print(f"[3] SDIO_Connect(0x9201) ph{phase}     -> {rc_str(rc)}")
            time.sleep(0.05)

        # 4) GetExtDeviceInfo (lecture capacités étendues)
        rc, data = dev.transaction(OP_SDIO_GET_EXT_DEVICE_INFO, params=[0x00C8])
        print(f"[4] SDIO_GetExtDeviceInfo(0x9202)-> {rc_str(rc)} ({len(data)} octets)")

        # 5) GetExtDevicePropDesc (lecture de quelques descripteurs sûrs)
        for code in (0x5013, 0xD211, 0xD241):
            rc, data = dev.transaction(
                OP_SDIO_GET_EXT_DEVICE_PROP_DESC, params=[code]
            )
            name = PROP_NAMES.get(code, f"0x{code:04X}")
            print(f"[5] GetExtDevicePropDesc {name:<28} "
                  f"-> {rc_str(rc)} ({len(data)} octets)")

    finally:
        # Fermeture propre de session (lecture seule).
        try:
            dev.transaction(OP_CLOSE_SESSION)
            print("\n[+] CloseSession(0x1003)         -> session fermée.")
        except PtpError:
            pass
        dev.close()


def main():
    ap = argparse.ArgumentParser(
        description="Sonde de diagnostic USB LECTURE SEULE pour Sony A6700."
    )
    ap.add_argument("--pid", type=lambda x: int(x, 0), default=None,
                    help="PID USB explicite (ex. 0x0DE7). Par défaut : auto.")
    ap.add_argument("--no-sdio", action="store_true",
                    help="S'arrêter après GetDeviceInfo (PTP standard seul).")
    args = ap.parse_args()

    try:
        run_probe(pid=args.pid, do_sdio=not args.no_sdio)
    except PtpError as e:
        sys.exit(f"[ERREUR] {e}")
    except usb.core.USBError as e:
        sys.exit(f"[ERREUR USB] {e}\n"
                 "Sous Windows : installez le pilote WinUSB sur l'interface "
                 "PTP du boîtier via Zadig (voir README.md).")


if __name__ == "__main__":
    main()
