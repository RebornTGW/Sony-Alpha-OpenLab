# A6700-Remote-Tools

Outils de **diagnostic en lecture seule** pour le dialogue USB (PTP / Sony « SDIO »)
avec un boîtier **Sony A6700 (ILCE-6700)**.

Ce dépôt sert à explorer le protocole de contrôle à distance de façon **sûre et
non destructive** : ouverture de session, lecture des informations device et des
descripteurs de propriétés étendues. Aucune commande d'écriture, de réglage ou de
déclenchement n'est émise.

> ⚠️ **Projet indépendant et non officiel.** Non affilié à Sony. Utilisation à vos
> risques, à des fins d'interopérabilité et d'étude personnelle.

---

## 🔒 Périmètre de sécurité

`probe_a6700.py` est **strictement en lecture seule** :

| Émis (lecture / négociation) | **Jamais émis** |
|---|---|
| `OpenSession` (0x1002) | `SetExtDevicePropValue` (0x9205) |
| `GetDeviceInfo` (0x1001) | `ControlDevice` (0x9207) → S1 / S2 / Movie Rec |
| `SDIO_Connect` (0x9201) | `SendObject`, suppression, formatage |
| `GetExtDeviceInfo` (0x9202) | mise à jour firmware, écriture réglages |
| `GetExtDevicePropDesc` (0x9203) | toute autre opération |
| `CloseSession` (0x1003) | |

Toute opération est validée contre une **liste blanche** (`READ_ONLY_OPS`) dans le
code : un opcode non listé lève une exception **avant** l'envoi au boîtier. La phase
de données PTP n'est utilisée qu'en **réception**.

Ce dépôt ne contient **aucun fichier extrait du firmware Sony** (voir `.gitignore`).
Les codes PTP employés sont des constantes de protocole publiques (PTP / ISO 15740)
et l'espace vendor Sony documenté de façon indépendante.

---

## 📦 Installation (Windows)

### 1. Python et dépendances

Python 3.9+ recommandé.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

`pyusb` nécessite la bibliothèque native **libusb-1.0**. Le plus simple sous Windows
est d'installer le pilote **WinUSB** sur l'interface du boîtier avec **Zadig** (étape
suivante) : pyusb utilisera alors le backend libusb fourni par WinUSB.
Si besoin, placez `libusb-1.0.dll` (64 bits) dans le dossier du script ou dans
`C:\Windows\System32`.

### 2. Pilote WinUSB via Zadig

Par défaut, Windows attache son propre pilote « appareil photo » (WPD/PTP) à
l'interface, ce qui empêche pyusb d'y accéder. Zadig permet de basculer cette
interface sur **WinUSB**.

1. Mettez le boîtier **sous tension** et réglez **Menu → Réseau/USB → Mode de
   connexion USB** sur **PC Remote** (ou **PC (PTP)**), puis reliez-le en USB.
2. Téléchargez Zadig depuis le site officiel : https://zadig.akeo.ie/
3. Lancez Zadig **en administrateur**.
4. Menu **Options → List All Devices**.
5. Dans la liste déroulante, sélectionnez l'interface du boîtier
   (p. ex. « ILCE-6700 » / « Sony … » ; interface PTP/Still Image).
6. À droite de la flèche, choisissez le pilote cible **WinUSB**.
7. Cliquez sur **Replace Driver** (ou **Install Driver**) et confirmez.

> 💡 **Réversible.** Pour rendre le boîtier de nouveau reconnu comme appareil photo
> normal par Windows : *Gestionnaire de périphériques → l'interface → Désinstaller
> le périphérique*, puis débranchez/rebranchez (Windows réinstalle son pilote WPD).
> Vous pouvez aussi simplement changer le mode USB du boîtier.

### Linux (alternative)

```bash
sudo apt install libusb-1.0-0
pip install -r requirements.txt
```
Donnez l'accès USB sans root via une règle udev :
```
# /etc/udev/rules.d/70-sony-a6700.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="054c", MODE="0660", GROUP="plugdev"
```
Au besoin, libérez l'interface de `gphoto2`/PTP (`gvfs-gphoto2`) avant exécution.

---

## ▶️ Utilisation

```powershell
# Détection automatique du boîtier Sony (VID 0x054C)
python probe_a6700.py

# PTP standard uniquement (s'arrête après GetDeviceInfo)
python probe_a6700.py --no-sdio

# Forcer un PID USB précis
python probe_a6700.py --pid 0x0DE7
```

### Sortie attendue (exemple)

```
=== probe_a6700 : diagnostic USB LECTURE SEULE ===

[+] Périphérique PTP ouvert (VID 0x054C PID 0x0DE7, interface #0).

[1] OpenSession(0x1002)          -> OK
[2] GetDeviceInfo(0x1001)        -> OK (512 octets)
      Fabricant        : Sony Corporation
      Modèle           : ILCE-6700
      Version firmware : 1.00
      N° de série      : xxxxxxxx
      Ext. vendor      : id=0x11 « Sony PTP Extensions »
      Opérations       : 42 (dont vendor 0x92xx : 30)
      Propriétés       : 7
[3] SDIO_Connect(0x9201) ph1     -> OK
[3] SDIO_Connect(0x9201) ph2     -> OK
[4] SDIO_GetExtDeviceInfo(0x9202)-> OK (900 octets)
[5] GetExtDevicePropDesc still_capture_mode (drive mode) -> OK (40 octets)
[5] GetExtDevicePropDesc aspect_ratio                    -> OK (28 octets)
[5] GetExtDevicePropDesc file_format_movie               -> OK (36 octets)

[+] CloseSession(0x1003)         -> session fermée.
```

(Les valeurs exactes dépendent du boîtier et de la version de firmware.)

---

## 📖 Référence — codes PTP clés (A6700)

Extraits par analyse statique indépendante. Codes de protocole uniquement
(aucune donnée de firmware embarquée). Voir le périmètre de sécurité ci-dessus :
seuls les codes de **lecture** sont émis par `probe_a6700.py` ; les « boutons »
`ControlDevice` sont **documentés mais jamais déclenchés** par cet outil.

### Opcodes d'opération

| Opcode | Opération | Type |
|---|---|---|
| 0x1001 | `GetDeviceInfo` | standard PTP (lecture) |
| 0x1002 / 0x1003 | `OpenSession` / `CloseSession` | standard PTP |
| 0x1009 / 0x101B | `GetObject` / `GetPartialObject` | standard PTP (lecture) |
| 0x9201 | `SDIO_Connect` | vendor Sony (handshake) |
| 0x9202 | `SDIO_GetExtDeviceInfo` | vendor Sony (lecture) |
| 0x9203 / 0x9204 | `GetExtDevicePropDesc` / `GetExtDevicePropValue` | vendor Sony (lecture) |
| 0x9205 | `SetExtDevicePropValue` | vendor Sony (**écriture — non utilisé**) |
| 0x9207 | `ControlDevice` | vendor Sony (**actionnement — non utilisé**) |

### Propriétés (`DevicePropCode`) — lecture

| Code | Nom symbolique | Usage |
|---|---|---|
| **0x5013** | `still_capture_mode` | mode Drive (single / continu / retardateur / **bracket**) |
| **0xD211** | `aspect_ratio` | ratio d'image (3:2 / 16:9 / 4:3 / 1:1) |
| **0xD241** | `file_format_movie` | format fichier film (XAVC HS / S / S-I) |
| **0xD242** | `recording_setting_movie` | réglage d'enregistrement (résolution / débit) |
| 0xD286 | `recording_frame_rate_setting_movie` | cadence film |
| 0xD253 / 0xD287 | `file_format_still` / `compression_file_format_still` | format photo |
| 0xD20D / 0xD21E | `shutter_speed` / `iso_sensitivity` | exposition |
| 0x5007 / 0x5010 | `f_number` / `exposure_bias_compensation` | exposition |

### Actions `ControlDevice` (⚠️ **écriture — documentées, non émises par cet outil**)

| Code | Nom symbolique | Effet |
|---|---|---|
| **0xD2C1** | `s1_button` | **demi-pression (AF)** |
| **0xD2C2** | `s2_button` | **pression complète (déclenchement photo)** |
| **0xD2C8** | `movie_rec_button` | **enregistrement vidéo start/stop** |
| 0xD2E6 | `s1_and_s2_button` | S1 + S2 combinés |
| 0xD2C3 / 0xD2C4 / 0xD2C9 | `ael_button` / `afl_button` / `fel_button` | verrous AE / AF / flash |

> Ces actions modifient l'état du boîtier (déclenchement, enregistrement). Elles
> sont listées ici **à titre de référence** et ne sont **pas** implémentées dans
> `probe_a6700.py`, qui reste strictement en lecture seule.

---

## 🛠️ Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| « Aucun périphérique USB Sony trouvé » | Boîtier éteint, en veille, ou câble data absent. Vérifier le mode USB = PC Remote. |
| `USBError: [Errno 5]` / access denied | Pilote WinUSB non installé sur l'interface → relancer Zadig. |
| « aucune interface PTP (classe 0x06) » | Mauvais mode USB (Mass Storage/MTP) → passer en PC Remote / PTP. |
| `NoBackendError` | `libusb-1.0.dll` introuvable → installer WinUSB (Zadig) ou déposer la DLL. |
| Timeout après OpenSession | Une autre application (Imaging Edge, gphoto2) occupe le boîtier → la fermer. |

---

## 📁 Contenu du dépôt

```
A6700-Remote-Tools/
├── probe_a6700.py     # sonde diagnostic USB lecture seule
├── requirements.txt   # dépendances Python (pyusb)
├── .gitignore         # exclusion stricte des binaires/firmware
├── LICENSE            # licence MIT
└── README.md
```

## Licence

Distribué sous licence **MIT** (voir [LICENSE](LICENSE)). Code original uniquement ;
aucun composant ni fichier issu du firmware Sony.
