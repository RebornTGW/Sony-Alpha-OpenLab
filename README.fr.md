# Sony-Open-Gate-Lab

**🌍 Langue : [English](README.md) · Français**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v0.1.0--alpha-blue.svg)](#)
[![Status](https://img.shields.io/badge/status-active%20development-orange.svg)](#)
[![Discord](https://img.shields.io/badge/Discord-Sony%20Alpha%20OpenLab-5865F2?logo=discord&logoColor=white)](https://discord.gg/Zr72h6AFa5)

Une **boîte à outils open-source pour les boîtiers Sony Alpha**, développée et testée
en priorité sur le **Sony A6700 (ILCE-6700)**, avec une architecture pensée pour
s'étendre progressivement aux autres boîtiers Sony.

La boîte à outils combine trois couches, chacune avec son propre niveau de sécurité :

- **Sonde USB en lecture seule** (PTP / Sony « SDIO ») — ouverture de session, lecture
  des informations device et des descripteurs de propriétés étendues ; aucune commande
  d'écriture, de réglage ou de déclenchement.
- **Multi-exposition de session (opt-in)** — capture encadrée + empilement local des
  trames ; session uniquement, rien n'est écrit de façon permanente sur le boîtier.
- **Recherche Open Gate RAM volatile** — lecture seule par défaut ; toute écriture est
  en RAM, opt-in, et effacée au redémarrage / retrait de batterie.

> ⚠️ **Projet indépendant et non officiel.** Non affilié à Sony. Utilisation à vos
> risques, à des fins d'interopérabilité et d'étude personnelle.
>
> 🚧 **Développement actif.** Ce projet est en développement actif et mis à jour
> régulièrement — attendez-vous à des changements fréquents tant que l'architecture
> se stabilise.

---

## ✅ État vérifié actuel (Sony A6700 v2.00)

Prouvé **en direct sur boîtier réel** (firmware 2.00, PC Remote `PID 0x0E78`) :

- **Télémétrie USB :** handshake OK ; **61 opcodes vendor `0x92xx`** énumérés ;
  `GetAllExtDevicePropInfo (0x9209)` ~8019 o (122 propriétés actives).
- **Contrôle capture :** `ControlDevice (0x9207)` S1 `0xD2C1` / S2 `0xD2C2` / movie-rec
  `0xD2C8` renvoient tous `OK`.
- **Récupération image :** vue pleine résolution lue sur `0xFFFFC001` (**~31,2 Mo RAW**),
  JPEG ou `.ARW`, via `GetObjectInfo` + `GetObject`.
- **Multi-exposition :** `multi_exposure.py` capture + les 4 modes de fusion Fujifilm
  (`additive`/`average`/`bright`/`dark`, + `screen`) fonctionnels de bout en bout.
- **Open Gate (recherche) :** tables capteur + encodeur pour **3840×2560** cartographiées
  en statique ; la bascule menu 3:2 est bloquée au niveau applicatif (HAITA) — voir
  [`docs/RESULTS.md`](docs/RESULTS.md). Voie RAM-only = recherche, non livrée.

---

## 🚀 Démarrage rapide (4 étapes)

1. **Installer** — Python 3.9+, puis `pip install -r requirements.txt`
   (voir [Installation](#-installation-windows)).
2. **Pilote** — mettre le boîtier en mode USB **PC Remote** et lier **WinUSB** à son
   interface avec **Zadig**. [Comment →](#2-pilote-winusb-via-zadig)
3. **Sonder (lecture seule)** — `python probe_a6700.py` pour valider le handshake USB
   et lister les propriétés exposées.
4. **Multi-exposition (opt-in)** — `python multi_exposure.py --shots 2 --live-overlay`
   pour capturer et fusionner les trames (session uniquement).

---

## 🎯 Périmètre du projet

La recherche est **strictement limitée à deux objectifs**, et **sans aucune
modification permanente** du boîtier :

1. **Open Gate 3:2** — étude de la faisabilité d'un enregistrement vidéo au format
   capteur 3:2 (« open gate »).
2. **Multi-exposition** — étude des mécanismes de capture multi-trames.

Ces deux objectifs sont abordés par **analyse statique** et par **diagnostic USB en
lecture seule**. Ce n'est pas un outil de contrôle général, de déclenchement, ni de
modification du firmware. Toute fonctionnalité future reste bornée à ces deux buts et
à l'approche de sécurité ci-dessous.

---

## 📷 Boîtiers pris en charge & feuille de route

La boîte à outils s'appuie sur le protocole distant Sony Alpha (PTP + extension
vendor Sony « SDIO ») et sur le chemin de correctif RAM Open Gate, tous deux
largement partagés sur la gamme **BIONZ XR**. 14 boîtiers BIONZ XR sont
catalogués dans [`cameras/`](cameras/), groupés par famille de capteur (famille
plus proche = disposition mémoire attendue plus proche de l'A6700 vérifié) :

| Famille de capteur | Boîtiers | Statut |
|---|---|---|
| APS-C 26 MP (IMX571) | **A6700** ✅, FX30, ZV-E10 II | A6700 vérifié (fw 2.00) ; les autres attendent `--dump-ram` / `--scan-dump` |
| Full-Frame 12,1 MP | A7S III, FX3, ZV-E1 | en attente de `--dump-ram` / `--scan-dump` |
| Full-Frame 33 MP | A7 IV, A7C II, FX2 | en attente de `--dump-ram` / `--scan-dump` |
| Full-Frame 61 MP | A7R V, A7CR | en attente de `--dump-ram` / `--scan-dump` |
| Full-Frame Stacked / GS | A1, A1 II, A9 III | en attente de `--dump-ram` / `--scan-dump` |

Les boîtiers **BIONZ X** plus anciens (A6400, A6600, ZV-E10 Mark I) sont une
génération de protocole différente et ne sont pas encore catalogués ici.

Deux catalogues distincts, volontairement :

- **[`cameras/`](cameras/)** — identité USB (VID/PID, handles de capture) pour
  les outils PTP/SDIO (`probe_a6700.py`, `experiment_a6700.py`,
  `multi_exposure.py`). Chargement via `from cameras import load_profile`.
- **[`profiles/`](profiles/)** (consommé par [`host-injector/`](host-injector/)) —
  les tables de correctifs RAM Open Gate. Seul `profile_4k_24p_stable` est
  vérifié ; les squelettes par boîtier (`fx30_v5.00`, `zve10m2_v1.00`,
  `fx2_v1.00`, `fx3_v6.00`, `a7m4_v4.00`) sont **verrouillés** : vrais
  identifiants d'étape, zéro écriture résolue, aucun offset inventé. Voir
  ["Contribuer un nouveau boîtier BIONZ XR"](#-contribuer-un-nouveau-boîtier-bionz-xr)
  ci-dessous.

> ✅ = activement testé · autres = prévus/placeholder. La compatibilité est validée
> boîtier par boîtier ; la présence d'un code dans le protocole ne signifie pas
> qu'il est exposé sur tous les modèles, et les codes modèle/PID des boîtiers
> non-A6700 sont à confirmer sur matériel réel. Vous voulez votre boîtier pris
> en charge ? Voir [Communauté & idées](#-communauté--idées).

---

## 🛰️ Contribuer un nouveau boîtier BIONZ XR

Un profil **squelette verrouillé** existe déjà dans [`profiles/`](profiles/) pour
chaque boîtier en attente (`fx30_v5.00`, `zve10m2_v1.00`, `fx2_v1.00`,
`fx3_v6.00`, `a7m4_v4.00`) : vrais identifiants d'étape (`L13`/`L16`/`S16`),
`"status": "experimental"`, et **zéro écriture résolue** — aucun offset mémoire
de ce dépôt n'a été deviné. `host-injector` refuse `--confirm-ram-write` sur un
profil à zéro écriture résolue, donc ces squelettes ne présentent aucun risque
tant que personne n'a encore touché le boîtier. Si vous avez un boîtier du
tableau ci-dessus et voulez aider à localiser ses adresses, en lecture seule, en
trois étapes :

1. **`--dump-ram`** — une fois en session Senser sur *votre* boîtier (même
   garde-fou `--allow-unverified-usb` que partout ailleurs), lisez une région
   candidate dans un fichier local :
   ```bash
   cargo run -- --dump-ram 0x02580cd8 0x40 --out dump_votre_boitier.bin \
     --senser-config senser_blobs.json --allow-unverified-usb
   ```
2. **`--scan-dump`** — entièrement hors-ligne, sans caméra : cherche dans un
   dump firmware (le vôtre, ou un plus complet déjà en main) les signatures
   d'octets « stock » du profil A6700 vérifié (`L13`/`L16`/`S16`), et produit un
   profil brouillon avec les offsets trouvés :
   ```bash
   cargo run -- --scan-dump dump_votre_boitier.bin --ref-profile profile_4k_24p_stable.json \
     --out brouillon_votre_boitier.json
   ```
   Une correspondance unique devient une écriture dans le brouillon ; une
   correspondance ambiguë ou absente est signalée dans `notes` plutôt que
   devinée — à résoudre à la main avant de leur faire confiance.
3. **`--verify-only`** — fusionnez les écritures résolues du brouillon dans le
   squelette de votre boîtier, puis confirmez que chaque site tient bien les
   octets stock attendus **avant** que quiconque essaie `--confirm-ram-write` :
   ```bash
   cargo run -- votre_boitier_v1.00 --verify-only --senser-config senser_blobs.json --allow-unverified-usb
   ```

**N'ajoutez pas** d'étape équivalente à `L19` sur le profil d'un nouveau
boîtier : sur l'A6700 vérifié, `L19` (l'encodeur high-speed uniquement) a
redémarré le noyau au passage STILL→MOVIE (voir [`RESEARCH.md`](RESEARCH.md)) ;
`M19` en était le remplaçant stable là-bas, et aucun boîtier non-A6700 n'a
d'équivalent `M19` confirmé pour l'instant non plus. Partagez vos résultats sur
le [Discord](https://discord.gg/Zr72h6AFa5) ou ouvrez une
[discussion GitHub](../../discussions) — voir
[Communauté & idées](#-communauté--idées) ci-dessous.

---

## 🧪 Approche sécurisée — RAM d'abord

Par mesure de sécurité, les fonctionnalités sont d'abord développées et testées
**uniquement en mémoire vive (RAM-only)** via USB :

- les changements vivent dans la RAM du boîtier et sont **effacés au redémarrage / au
  retrait de la batterie** ;
- **rien n'est écrit en mémoire persistante ni dans le firmware** ;
- un **mode permanent ne serait envisagé que plus tard**, si et seulement si la
  sécurité et la stabilité sont **totalement prouvées** — et même alors, de manière
  explicite et optionnelle.

L'outil de référence actuel (`probe_a6700.py`) va plus loin : il est strictement
**en lecture seule** et n'effectue aucune écriture, même en RAM.

---

## 🔒 Périmètre de sécurité (sonde lecture seule)

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

> ⚠️ **Un pilote WinUSB par PID USB.** Le boîtier expose un **PID USB différent selon
> le mode**, et Windows traite chaque PID comme un périphérique distinct — on lie donc
> **WinUSB / libusb-win32** une fois par PID :
>
> | PID | Mode | Utilisé par |
> |---|---|---|
> | `054C:0E78` | PC Remote | `probe_a6700.py`, `multi_exposure.py` |
> | `054C:0E76` | Mass Storage | `ram_opengate.py`, `opengate_inject.py` (entrée) |
> | `054C:0336` | Mode service | voie Open Gate RAM (réénumère depuis `0E76`) |
>
> Relancez Zadig et liez **WinUSB** à nouveau après un changement de mode / quand un
> nouveau PID apparaît. Pour annuler une liaison : *Gestionnaire de périphériques →
> l'interface → Désinstaller le périphérique* → débrancher/rebrancher.

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

# Listes de codes complètes (tous les opcodes vendor & toutes les propriétés)
python probe_a6700.py --verbose

# Envoyer aussi le handshake SDK (SetRemoteSdkInfo 0x9214, écriture de session)
python probe_a6700.py --sdk-handshake

# Forcer un PID USB précis
# (A6700 en mode PC Remote = 0x0E78, confirmé sur firmware 2.00)
python probe_a6700.py --pid 0x0E78
```

Sur l'A6700, `GetExtDevicePropValue (0x9204)` renvoie `0x2005` (Operation Not
Supported) ; la sonde lit donc les **vraies valeurs courantes depuis le flux
`GetAllExtDevicePropInfo (0x9209)`** à l'étape `[5b]` (pour `still_capture_mode`,
`aspect_ratio`, `file_format_movie`, `recording_setting_movie`,
`recording_frame_rate_setting_movie`), décode des entrées en `[4c]`, et teste aussi
`GetExtDeviceProp (0x9251)` en lecture seule en `[5c]`. `--sdk-handshake` est la seule
exception à la lecture seule par défaut (voir la note ci-dessus) ; tout le reste de la
sonde demeure en lecture seule.

Les listes de codes (opcodes vendor en `[2b]`, propriétés exposées en `[4]`/`[4b]`)
sont **compactes par défaut** ; `--verbose` affiche la liste complète code par code.
L'étape `[4b]` exécute `SDIO_GetAllExtDevicePropInfo (0x9209)` (lecture seule) pour
montrer quelles propriétés vidéo `0xD2xx` le boîtier remonte dans son flux global.

> ℹ️ **À propos des propriétés vidéo & de `SetRemoteSdkInfo (0x9214)`.** Sur l'A6700,
> `file_format_movie (0xD241)` / `recording_setting_movie (0xD242)` peuvent renvoyer
> un descripteur vide même avec le sélecteur sur Vidéo/M. L'analyse statique de
> `libInfraRemote.so` montre que la visibilité d'une propriété dépend d'un flag
> `IsEnable` par propriété (`MrpwDeviceManager::UpdateInternalPropValueAndIsEnable`)
> lié à l'état du boîtier, et que `SetRemoteSdkInfo (0x9214)` est l'étape de
> handshake qui déclare la version/modèle du SDK hôte. `0x9214` **envoie des données
> au boîtier** (handshake de session, pas une écriture de réglage) ; il est donc
> volontairement **exclu de la liste blanche lecture seule** — l'activer serait une
> option explicite séparée.

> 📌 **PID A6700 connu :** `0x0E78` en mode USB **PC Remote** (confirmé en direct sur
> firmware **2.00**). Le PID diffère selon le mode de connexion USB et le boîtier.
>
> ✅ **Validé en direct (A6700, firmware 2.00).** La séquence complète en lecture
> seule a été confirmée sur boîtier réel : `SDIO_Connect(0x9201)` ph1/ph2/ph3
> renvoient chacune `OK (8 bytes data)`, `SDIO_GetExtDeviceInfo(0x9202)` renvoie
> ~826 octets, `GetAllExtDevicePropInfo(0x9209)` renvoie ~8019 octets (122 propriétés
> actives en mode Vidéo), et `GetExtDevicePropDesc` décode la valeur courante + les
> valeurs autorisées (ex. `still_capture_mode` en énum propre, `aspect_ratio`).
> `GetExtDevicePropValue (0x9204)` est **non supporté** sur ce dataset (`0x2005`) ;
> les valeurs courantes se lisent donc dans le flux `0x9209`.
>
> ✅ **Contrôle validé (écritures de session).** Les déclenchements `ControlDevice
> (0x9207)` ont été confirmés `OK` sur boîtier : **S1** (`0xD2C1`) + **S2** (`0xD2C2`)
> press/release (capture multi-vues) et **enregistrement vidéo** (`0xD2C8`)
> start/stop. Le contrôle USB complet de la capture et de l'enregistrement fonctionne.
>
> 🔒 **Verrou applicatif HAITA prouvé.** `SetExtDevicePropValue(0xD211)` avec `1`
> (3:2) renvoie `OK`, mais la relecture via `0x9209` montre qu'`aspect_ratio` reste à
> `2` (16:9) en mode Vidéo. Cela confirme expérimentalement que le **HAITA Feature
> Manager** (`REC_MOVIE_ASPECT_RATIO_NOT_16_9`) filtre la bascule 3:2 au niveau
> applicatif (`appFw.so`), au-delà du protocole PTP : la commande est acceptée puis
> silencieusement ignorée. L'Open Gate 3:2 vidéo **n'est pas** atteignable par une
> simple écriture de propriété.

### Sortie attendue (exemple, A6700 firmware 2.00)

```
=== probe_a6700: READ-ONLY USB diagnostic ===

[+] PTP device opened (VID 0x054C PID 0x0E78, interface #0).

[1] OpenSession(0x1002)          -> OK
[2] GetDeviceInfo(0x1001)        -> OK (… bytes)
      Manufacturer     : Sony Corporation
      Model            : ILCE-6700
      Firmware version : 2.00
      Serial number    : xxxxxxxx
      Vendor extension : id=0x11 "Sony PTP Extensions"
      Operations       : … (vendor 0x92xx: 61)
      Properties       : …

[2b] Vendor operations 0x92xx (61):
       0x9201  SDIO_Connect
       0x9202  SDIO_GetExtDeviceInfo
       0x9203  GetExtDevicePropDesc
       …       …
[3] SDIO_Connect(0x9201) ph1     -> OK
[3] SDIO_Connect(0x9201) ph2     -> OK
[4] SDIO_GetExtDeviceInfo(0x9202)-> OK (… bytes)
[3] SDIO_Connect(0x9201) ph3     -> OK
[5] GetExtDevicePropDesc still_capture_mode (drive mode) -> OK (… bytes)
[5] GetExtDevicePropDesc aspect_ratio                    -> OK (… bytes)
[5] GetExtDevicePropDesc file_format_movie               -> OK (… bytes)

[+] CloseSession(0x1003)         -> session closed.
```

(Les valeurs exactes dépendent du boîtier et de la version de firmware. Les messages
de la sonde sont en anglais.)

---

## 📖 Référence — codes PTP clés (A6700)

Extraits par analyse statique indépendante. Codes de protocole uniquement
(aucune donnée de firmware embarquée). Seuls les codes de **lecture** sont émis par
`probe_a6700.py` ; les « boutons » `ControlDevice` sont **documentés mais jamais
déclenchés** par cet outil.

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
| « No Sony USB device found » | Boîtier éteint, en veille, ou câble data absent. Vérifier le mode USB = PC Remote. |
| `USBError: [Errno 5]` / access denied | Pilote WinUSB non installé sur l'interface → relancer Zadig. |
| « no usable PTP interface » | Mauvais mode USB (Mass Storage/MTP) → passer en PC Remote / PTP. |
| `NoBackendError` | `libusb-1.0.dll` introuvable → installer WinUSB (Zadig) ou déposer la DLL. |
| Timeout après OpenSession | Une autre application (Imaging Edge, gphoto2) occupe le boîtier → la fermer. |

---

## 🧪 Expérimentations de session (`experiment_a6700.py`)

`probe_a6700.py` reste **strictement en lecture seule**. Pour des tests contrôlés qui
**écrivent** réellement dans le boîtier, un script **séparé** `experiment_a6700.py`
effectue des opérations **de session, non persistantes** (tout ce qu'il modifie vit
en RAM et est effacé au redémarrage / retrait de batterie — rien n'est écrit en
mémoire ni dans le firmware).

Il refuse de s'exécuter sans le drapeau explicite **`--confirm-session-write`**, et
affiche le code de retour PTP de chaque opération.

```powershell
# Tenter de passer aspect_ratio (0xD211) en 3:2 en mode Vidéo, puis relire
python experiment_a6700.py --confirm-session-write --test-aspect-3-2

# Déclenchement multi-vues contrôlé : réglage drive optionnel + séquence S1/S2
python experiment_a6700.py --confirm-session-write --test-burst-trigger --drive-value 0x2

# Enregistrer un court clip pour inspecter la résolution du MP4 sur la carte SD
python experiment_a6700.py --confirm-session-write --test-movie-rec --rec-seconds 2
```

| Expérimentation | Ce qu'elle fait (session uniquement) |
|---|---|
| `--test-aspect-3-2` | lit la valeur courante d'`aspect_ratio` (0xD211) depuis le flux `0x9209`, `SetExtDevicePropValue(0x9205)` écrit `1` (3:2), relit, et indique si le boîtier a réellement basculé `2`→`1` ou s'il a accepté-puis-ignoré. |
| `--test-burst-trigger` | règle éventuellement `still_capture_mode` (0x5013) via `--drive-value`, puis exécute `ControlDevice(0x9207)` : `S1` (0xD2C1) press/release + `S2` (0xD2C2) press/release. |
| `--test-movie-rec` | bascule `movie_rec_button` (0xD2C8) via `ControlDevice(0x9207)` pour démarrer, attend `--rec-seconds`, puis arrête — pour vérifier la résolution réelle du MP4 enregistré (ex. après `--test-aspect-3-2`). |

> ⚠️ Ces écritures modifient l'**état de session en direct** (et `--test-burst-trigger`
> **prend une photo**). Elles sont volatiles, mais à utiliser délibérément, sur votre
> propre matériel, sans contenu de carte important. Les valeurs S1/S2 et le payload
> SDK sont best-effort et peuvent nécessiter un ajustement selon le boîtier. Voir
> [`CONTRIBUTING.fr.md`](CONTRIBUTING.fr.md).

---

## 🎞️ Multi-exposition automatisée (`multi_exposure.py`)

Bâti sur les commandes de contrôle de session **validées** (`still_capture_mode`
0x5013 + `ControlDevice` 0x9207 S1/S2), `multi_exposure.py` capture **N vues à
intervalle contrôlé** et peut les **empiler** localement avec les quatre **modes de
multi-exposition Fujifilm**. Il exige `--confirm-session-write` et prend de vraies photos.

### Modes de multi-exposition Fujifilm (`--stack-mode`)

Tout l'empilement se fait en **float32 linéaire** (JPEG 8 bits, ou RAW/TIFF 16 bits
décodés si `rawpy`/`tifffile` sont installés), pour éviter le banding dans les ombres.

| Mode | Alias | Calcul | Idéal pour |
|---|---|---|---|
| `additive` | | `clip(ΣvueN)` | multi-exposition additive façon film |
| `average` | | `Σvue / N` | équilibré, multi-exposition classique |
| `bright` | `lighten` | **max** par pixel | filés d'étoiles, sujet clair sur fond sombre |
| `dark` | `darken` | **min** par pixel | silhouettes sur fond clair |
| `screen` | | `1-(1-A)(1-B)` | rendu double-exposition doux Fuji/Canon |

> ⚠️ **`additive` ajoute de la lumière.** Deux vues ajoutent ~**+1 EV**, N vues
> **+log₂(N) EV**. Réglez une compensation d'exposition négative sur le boîtier ou les
> hautes lumières saturent — l'outil affiche la valeur exacte quand vous choisissez
> `additive`.

```powershell
# 5 vues, 1 s d'intervalle (AF avant chaque prise)
python multi_exposure.py --confirm-session-write --shots 5 --interval 1.0

# Multi-exposition additive façon film, téléchargement auto de chaque vue (0xFFFFC001)
python multi_exposure.py --confirm-session-write --shots 4 --no-af \
    --download-dir out/ --stack out/multi.png --stack-mode additive

# HORS-LIGNE filé d'étoiles : empiler un dossier, sans boîtier (bright = max par pixel)
python multi_exposure.py --stack-dir ./frames --stack trails.png --stack-mode bright

# --stack-all : rendre les 4 modes de base à partir des mêmes vues pour comparer
python multi_exposure.py --stack-dir ./frames --stack out/me.png --stack-all
#   -> out/me_additive.png  out/me_average.png  out/me_bright.png  out/me_dark.png

# Fusion RAW linéaire HORS-LIGNE en 16 bits : 2 à 9 fichiers Sony .ARW -> TIFF 16 bits
python multi_exposure.py --raw-blend frame1.ARW frame2.ARW frame3.ARW \
    --mode avg --output out/merged.tiff
# Modes RAW : dark, bright, avg, add

# Pas-à-pas Fujifilm : [Entrée] suivante / [r] refaire la dernière / [q] finir & fusionner
python multi_exposure.py --confirm-session-write --interactive --shots 3 \
    --download-dir out/ --stack out/double.png --stack-mode screen

# Aperçu Live View superposé en temps réel (aligner la Vue 2 ; Espace = déclencher)
python multi_exposure.py --confirm-session-write --live-overlay --shots 2 \
    --download-dir out/ --stack out/double.png --stack-mode screen --overlay-opacity 0.5

# Aperçu fantôme manuel : index webcam, vidéo ou dossier d'images
python multi_exposure.py --live-ghost --source 0 --shots 3 --mode avg
# Aperçu hors ligne (un .ARW montre son aperçu JPEG embarqué) ;
# Espace fige, S sauve en avance (>= 2 prises), R réinitialise, Q quitte
python multi_exposure.py --live-ghost --source ./frames --shots 3 --mode bright

# --live-ghost + -o : un dossier de .ARW + une sortie .tiff lance l'empilement
# RAW 16 bits linéaire complet (blend_raw_files) une fois --shots atteint ou
# via S ; toute autre combinaison source/sortie sauve l'aperçu composité
python multi_exposure.py --live-ghost --source ./raw_frames --shots 3 --mode add -o out/ghost.tiff
```

| Option | Rôle |
|---|---|
| `--shots N` / `--interval S` | capture N vues, espacées de S secondes |
| `--no-af` | saute le demi-appui S1 (AF) ; S2 pleine pression seulement |
| `--drive-value V` | règle `still_capture_mode` (0x5013) d'abord (valeur d'énum continu/bracket) |
| `--download-dir DIR` | télécharge auto chaque vue via le handle Sony `0xFFFFC001` (`GetObject`, lecture seule) |
| `--stack OUT` / `--stack-dir DIR` | fichier de sortie / dossier source hors-ligne |
| `--stack-mode` | `additive`, `average`, `bright`/`lighten`, `dark`/`darken`, `screen` |
| `--stack-all` | rend les 4 modes Fujifilm de base à partir des mêmes vues |
| `--interactive` / `--manual-step` | pas-à-pas : `[Entrée]` suivante / `[r]` refaire la dernière / `[q]` finir & fusionner |
| `--live-overlay` / `--overlay-opacity` | fenêtre live superposant le flux (`0xFFFFC002`) sur la Vue 1 ; Espace déclenche |
| `--live-ghost` / `--source` | aperçu OpenCV depuis une webcam (p. ex. `0`), vidéo ou dossier d'images (`.ARW` via son aperçu JPEG embarqué) ; `--shots` de 2 à 9 ; Espace capture, `S` sauve en avance, `R` réinitialise, `Q` quitte |
| `-o` / `--output` | avec `--raw-blend` : sortie `.tiff` requise. Avec `--live-ghost` : facultative - sauvée en atteignant `--shots` ou via `S` ; un empilement RAW `.tiff` si chaque prise était un `.ARW`, sinon l'aperçu composité |

**Expérience double exposition native.** `--interactive` reproduit le flux Fujifilm :
prendre la Vue 1, puis pour chaque vue suivante choisir `[Entrée]` pour déclencher,
`[r]` pour refaire la dernière, ou `[q]` pour terminer — un aperçu est écrit après
chaque prise pour juger la composition. `--live-overlay` va plus loin : il superpose le
Live View en temps réel sur la/les vue(s) précédente(s) pour aligner avant d'appuyer sur
**Espace**. La fenêtre utilise `tkinter` (fourni avec Python) + Pillow — aucune
dépendance supplémentaire.

`--live-ghost` est un aperçu manuel séparé, depuis une webcam/UVC ou une vidéo/un
dossier d'images hors ligne. Il superpose la vue courante aux prises mémorisées et
affiche le HUD `Manual k/N exp. [mode]`. Un dossier de fichiers Sony `.ARW` fonctionne
aussi : l'aperçu JPEG embarqué de chacun (`extract_thumb()` de `rawpy`) est décodé pour
la fenêtre live — un fichier sans aperçu JPEG, ou `rawpy` absent, est ignoré avec un
message clair plutôt que de faire échouer toute la session. Installez les dépendances
facultatives avec `pip install opencv-python rawpy` ; **Espace** fige une prise, **S**
sauve en avance (nécessite `-o` et >= 2 prises), **R** réinitialise et **Q** quitte.
Modes disponibles : `dark`, `bright`, `avg` et `add`.

**Sauvegarder un résultat `--live-ghost` (`-o`).** Atteindre `--shots` sauve
automatiquement (puis termine la session, comme `S` immédiatement suivi de `Q`) ; `S`
sauve en avance dès 2 prises capturées, sans terminer la session. Ce qui est écrit
dépend des sources capturées : si chacune était un fichier `.ARW` (cas du dossier de
RAW) *et* que `-o` finit en `.tiff`, la sauvegarde lance le même empilement RAW 16 bits
linéaire pleine résolution (`blend_raw_files`) que `--raw-blend` - pas l'aperçu JPEG
basse résolution. Tout autre cas (webcam/vidéo, mélange, ou sortie non-`.tiff`) sauve
l'image composite qu'OpenCV a déjà à l'écran.

**Téléchargement auto (PC Remote).** En mode PC Remote, l'A6700 n'expose pas
`GetObjectHandles` ; il place la dernière image capturée sur le handle Sony spécial
**`0xFFFFC001`**, que `--download-dir` lit après chaque prise via `GetObject`. Le
buffer 26 Mpx n'est pas prêt instantanément : chaque sondage appelle d'abord
**`GetObjectInfo (0x1008)`** (le boîtier ne dimensionne l'objet qu'une fois interrogé)
et ne télécharge que si la taille > 0, jusqu'à ~3 s. Le fichier garde sa vraie
extension via `GetObjectInfo` — **JPEG ou RAW `.ARW`** (pas seulement `FF D8`). Pour
router les images même si le menu est sur « Caméra seule », l'outil envoie
`SetContentsTransferMode (0x9212)` à la connexion (désactivable avec `--no-pc-transfer` ;
essayez `--xfer-mode 2` si le mode 1 ne route pas). `--verbose` affiche les codes de
retour et tailles par sondage. Régler la **Destination d'enregistrement sur
« PC + Caméra » ou « PC seul »** reste le plus fiable.

**Empilement hors-ligne.** `--stack-dir DIR --stack OUT` (sans
`--confirm-session-write`) empile les images d'un dossier **sans toucher au boîtier** —
ex. des vues copiées de la carte SD. Nécessite Pillow + numpy (`pip install pillow numpy`).

---

## 🖥️ HUD de monitoring & bascule rapide (`monitor_hud.py`)

Un overlay sombre à l'écran pour le cadrage et la bascule instantanée de mode
pendant la prise de vue — webcam/capture HDMI, un fichier vidéo, ou un dossier
d'images/`.ARW`. Il ne touche jamais lui-même la RAM de la caméra : chaque
action matériel réel est un simple appel au sous-processus `opengate-rs.exe`,
via les options déjà verrouillées de cet outil (`--confirm-ram-write`, etc.) —
le HUD n'invente aucun nouveau chemin d'écriture.

```bash
# Mode démo : image de test 3:2 synthétique, bascule simulée, sans caméra
python monitor_hud.py --demo

# Webcam / carte de capture HDMI comme source de monitoring
python monitor_hud.py --source 0 --exe host-injector/target/release/opengate-rs.exe

# Un dossier de vues (ou de fichiers .ARW - affichés via leur aperçu JPEG embarqué)
python monitor_hud.py --source ./frames
```

| Touche | Fait |
|---|---|
| `1` | Bascule rapide → Stock 16:9 (`3840x2160`). **Aucune restauration logicielle n'existe** — ce projet est RAM uniquement par conception ; la vraie restauration est un redémarrage à froid / retrait de la batterie (~10 s). `--demo` lance `--plan` à vide à la place. |
| `2` | Bascule rapide → 4K Open Gate 3:2 (`3840x2560`). Sur matériel réel, nécessite une confirmation explicite dans le HUD avant de lancer `--confirm-ram-write` ; `--demo` lance `--plan` à vide. |
| `3` | Bascule rapide → superposition Live Ghosting / Multi-exposition (réutilise les modes de fusion de `multi_exposure.py`) |
| `H` | affiche/masque le menu de bascule rapide |
| `G` | fait défiler les guides de cadrage : **Tous** (3:2 + 16:9 + 9:16) → **16:9 seul** → **9:16 seul** → **Désactivé** |
| `I` | affiche/masque le badge de statut en haut à droite (état RAM · profil actif · `DEMO`/`LIVE USB`) |
| `W` | affiche/masque le waveform de luminance en bas à gauche (0–100 IRE, désactivé par défaut) |
| `M` | (mode 3) fait défiler le mode de fusion du fantôme : `dark` → `bright` → `avg` → `add` |
| `Espace` | (mode 3) fige la vue courante comme référence fantôme |
| `Q` | quitte |

**Les guides de cadrage** dessinent les trois recadrages Open Gate à la fois
par défaut : le cadre 3:2 complet, un recadrage centré 16:9 (exactement
`3840x2160` sur le capteur réel — la résolution stock, en letterbox haut/bas
avec coins repères), et un recadrage centré 9:16 (exactement `1440x2560`, en
pillarbox gauche/droite) pour le cadrage vertical Reels/Shorts — tout calculé
à partir de la taille réelle de la vue, donc le même calcul tient aussi en
`--demo` à une résolution plus petite.

**Le waveform** est un scope de luminance compact (BT.601, échantillonné par
colonne la plus proche — suffisant pour juger l'exposition d'un coup d'œil,
pas un outil de qualité broadcast) avec une ligne rouge à **94 IRE**, le point
de clip des hautes lumières en S-Log3.

Nécessite OpenCV (`pip install opencv-python`) ; les aperçus de dossier `.ARW`
nécessitent `rawpy` (comme pour `--live-ghost` ci-dessus).

---

## 📱 Chargement RAM-only mobile (sans PC, en déplacement)

La session est **volatile** (perdue à l'extinction) ; la charger sur le terrain est le
but. Voies prévues/expérimentales — **brancher ~2 s, débrancher, filmer jusqu'à
l'extinction** :

- **Android (USB-C OTG) :** l'outil Python via Termux, ou une page WebUSB dans
  Chrome — sans app store.
- **iPhone (USB-C, 15/16) :** une petite app compagnon (compilée via GitHub Actions /
  sideload) joue la même séquence USB.
- **Dongle de poche (ESP32-S3 USB-C) :** une clé autonome qui rejoue la session au
  branchement — 100 % sans PC.

> Ces voies sont sur la feuille de route ; la CLI bureau est la référence aujourd'hui.
> Voir [`docs/ROADMAP.md`](docs/ROADMAP.md).

---

## 🎬 Post-traitement (DaVinci Resolve / lecteurs)

Les clips Open Gate 3:2 peuvent nécessiter une correction de conteneur sans perte pour
certains éditeurs/lecteurs — sans réencodage, simple remux :

```bash
ffmpeg -i input.mp4 -map 0:v:0 -map 0:a? -c copy -movflags +faststart output.mp4
```

### Correction verticale + livraison simultanée 3:2 / 16:9 / 9:16

Le clip stable **3840×2560** utilise la fenêtre capteur contribuée (5952×**3876**),
qui ne capte que `3876 / 3968 = 0,977` du champ 3:2 natif — l'image est donc
**~2,4 % trop haute**. Corrigez en écrasant la hauteur à **97,7 %**, puis coupez
chaque format depuis ce seul master :

```bash
# 0) Un master 3:2 corrigé (3840x2560 -> hauteur x0,977), scaler de qualité
ffmpeg -i opengate.mp4 -vf "scale=3840:2502:flags=lanczos,setsar=1" \
       -c:v prores_ks -profile:v 3 -c:a copy master_3x2.mov

# 1) trois livrables depuis le master corrigé, en UNE passe (pas de perte en chaîne)
ffmpeg -i master_3x2.mov -filter_complex "\
  [0:v]crop=3840:2502[c32]; \
  [0:v]crop=3840:1408:0:(ih-1408)/2[c169]; \
  [0:v]crop=1408:2502:(iw-1408)/2:0[c916]" \
  -map "[c32]"  -c:v prores_ks -profile:v 3 deliver_3x2.mov \
  -map "[c169]" -c:v prores_ks -profile:v 3 deliver_16x9.mov \
  -map "[c916]" -c:v prores_ks -profile:v 3 deliver_9x16.mov
```

| Sortie | Recadrage depuis le master corrigé 3840×2502 | Usage |
|---|---|---|
| **3:2** | image entière `3840×2502` | le rendu open gate, natif sur l'écran arrière |
| **16:9** | centre `3840×1408` (haut/bas rognés) | livraison vidéo standard |
| **9:16** | centre `1408×2502` | vertical / réseaux, recadré depuis la capture plus haute |

> Tout l'intérêt de l'open gate : filmer le master 3:2 **une seule fois**, puis
> recadrer 16:9 et 9:16 dans la résolution verticale en plus au lieu de refilmer. La
> fenêtre 3:2 exacte expérimentale (5952×3968) supprime l'étape des 97,7 % — voir
> [`RESEARCH.md`](RESEARCH.md).

---

## 🧬 Open Gate 3:2 RAM volatile (recherche, `ram_opengate.py`)

Cible : **ILCE-6700 firmware 2.00**, 3840×2160 → **3840×2560** en RAM uniquement
(**effacé à l'extinction / retrait batterie**). L'Open Gate est verrouillé au niveau
applicatif (HAITA, `REC_MOVIE_ASPECT_RATIO_NOT_16_9` dans `appFw.so`) ; cet outil vise
le mot de hauteur de l'encodeur en aval.

**Fonctionnement réel (BIONZ XR).** Ce n'est pas un « poke mémoire » côté PC. Le
pipeline vérifié (tel qu'utilisé par le kit GPL
[ArcaneLantern](https://github.com/ArcaneLantern/a6700-open-gate-test) — *référencé,
jamais copié*) : **Mass Storage** (`PID 0x0E76`) → **mode service** Sony (réénumère en
`PID 0x0336`, via [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE), MIT) → un petit
**helper ARM64 embarqué** est téléversé, exécuté une fois, et c'est *lui* qui lit/écrit
la RAM du boîtier, laissant un fichier résultat sur le disque RAM.

> **Cette version MIT ne fournit aucun helper embarqué** (un helper correct embarque des
> tables dérivées du firmware Sony ; les builds vérifiés sont GPL). `ram_opengate.py`
> fournit donc le **côté hôte** MIT : la carte d'adresses 2.00 vérifiée + les dimensions,
> une sonde SCSI lecture seule, un scanner de signature ARM64, et la logique
> verify/patch/restore via un transport `CameraMemory` enfichable. La lecture/écriture
> RAM **refuse tant qu'aucun transport n'est branché** — elle ne devine jamais.

```bash
# Sans boîtier : affiche les faits 2.00 vérifiés + la première commande à lancer
python ram_opengate.py --info

# Sonde SCSI lecture seule (basculez d'abord le mode USB sur Mass Storage)
python ram_opengate.py --probe-msc

# Lecture seule (défaut) : lit + vérifie les sites de hauteur de l'encodeur
python ram_opengate.py --verify-only

# Patch volatile opt-in (0x0870 2160 -> 0x0A00 2560) : vérifie le stock, sauvegarde,
# écrit, relit. Nécessite un transport CameraMemory branché.
python ram_opengate.py --confirm-ram-write

# Revert en RAM sans redémarrer
python ram_opengate.py --restore
```

> ⚠️ **Réserves non vérifiées (A6700 2.00).** La fenêtre 4K contribuée rend l'image
> **~2,4 % trop haute** ; la **fenêtre 3:2 exacte n'a jamais tourné sur un A6700** (image
> noire / redémarrage possibles — un retrait batterie corrige) ; la lecture 3840×2560
> en boîtier exige un correctif séparé. Code MIT uniquement, zéro octet firmware, zéro
> écriture flash.

### Injecteur mono-session (`opengate_inject.py`) + profils déclaratifs

`ram_opengate.py` prouve un seul site ; `opengate_inject.py` applique un **profil
entier en une seule session service tenue** — le boîtier passe en mode service une
fois et les écritures de chaque étape s'enchaînent en RAM, supprimant les
débranchements manuels entre étapes. Les tables de patch vivent en données brutes
dans [`profiles/`](profiles/) :

| Profil | État | Quoi |
|---|---|---|
| `profile_4k_24p_stable` | **vérifié** | 3840×2560 via la chaîne stable M19 (enregistrement propre) |
| `profile_true_3x2_experimental` | expérimental | fenêtre exacte 5952×3968 (jamais lancée) |
| `playback_fix` | expérimental | module optionnel R19 de lecture en boîtier |

Les mots de géométrie portent des octets cibles littéraux (arithmétique à partir de
la résolution) ; les blobs encodeur/capteur/lecture dérivés du firmware **ne sont pas
dans ce dépôt** — chaque étape référence un `payloads/*.bin` (git-ignoré) vérifié par
sha256. Le pré-vol contrôle NTSC/PAL vs les cadences du profil et la molette
STILL/MOVIE avant toute écriture.

```bash
# Sans boîtier : affiche le plan d'écriture résolu + le pré-vol (défaut)
python opengate_inject.py profile_4k_24p_stable --video-standard NTSC --dial MOVIE

# Lister les profils fournis
python opengate_inject.py --list

# Lecture seule sur boîtier : confirme que chaque site est au stock
python opengate_inject.py profile_4k_24p_stable --verify-only

# Application opt-in (nécessite un transport CameraMemory branché ; verify -> backup -> write -> readback)
python opengate_inject.py profile_4k_24p_stable --confirm-ram-write
```

Voir [`RESEARCH.md`](RESEARCH.md) pour les découvertes matérielles derrière ces
profils (dalles, reboot L19-vs-M19, le buffer de 3980 lignes qui accueille le vrai 3:2).

**Sur le terrain (sans PC).** Une fois vérifié sur PC, le patch volatile peut tourner
depuis un téléphone en **USB-C OTG** (Android + Termux + `pyusb`/PMCA-RE côté hôte).
L'étape du helper embarqué reste nécessaire — le kit ArcaneLantern fournit une APK
Android qui l'exécute ; cet outil MIT couvre la sonde/vérif lecture seule sur le même
téléphone.

---

## 💬 Communauté & idées

Les idées de fonctionnalités ou de boîtiers à prendre en charge sont les bienvenues :

- **💡 Demandes de fonctionnalités & de boîtiers** — ouvrez une
  [GitHub Issue](../../issues) ou lancez une
  [GitHub Discussion](../../discussions). Indiquez votre boîtier, la version de
  firmware et ce que vous aimeriez voir (ex. « ajouter le support A7 IV »,
  « tester l'Open Gate sur FX30 »).
- **🗨️ Discord communautaire** — rejoignez **Sony Alpha OpenLab** pour coordonner les
  tests et partager les résultats : **https://discord.gg/Zr72h6AFa5**

Merci de lire [`CONTRIBUTING.fr.md`](CONTRIBUTING.fr.md) avant d'ouvrir une pull request.

---

## 📚 Documentation

- [`RESEARCH.md`](RESEARCH.md) — **découvertes matérielles inédites A6700 2.00** :
  dalles d'affichage (arrière 3:2 / EVF 4:3), diagnostic du reboot noyau L19-vs-M19,
  et le calcul du buffer `dmmwb` de 3980 lignes qui ouvre la voie au vrai 3:2.
- [`profiles/README.md`](profiles/README.md) — format des tables de patch Open Gate déclaratives.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) (FR) / [`docs/ROADMAP.en.md`](docs/ROADMAP.en.md) (EN)
  — jalons accomplis et prochaines étapes (portabilité, étude Open Gate, autres boîtiers).
- [`docs/RESULTS.md`](docs/RESULTS.md) (FR) / [`docs/RESULTS.en.md`](docs/RESULTS.en.md) (EN)
  — **résultats expérimentaux** validés en direct sur l'A6700 (succès
  multi-exposition, verrou HAITA 3:2).
- [`docs/PROTOCOL.md`](docs/PROTOCOL.md) (FR) / [`docs/PROTOCOL.en.md`](docs/PROTOCOL.en.md) (EN)
  — architecture du protocole PTP / « SDIO ».
- [`docs/DEVICE_PROPERTIES.md`](docs/DEVICE_PROPERTIES.md) (FR) /
  [`docs/DEVICE_PROPERTIES.en.md`](docs/DEVICE_PROPERTIES.en.md) (EN)
  — table complète des **386 codes** `DevicePropCode` / contrôle.
- [`CONTRIBUTING.fr.md`](CONTRIBUTING.fr.md) (FR) / [`CONTRIBUTING.md`](CONTRIBUTING.md) (EN)
  — règles de contribution.

## 📁 Contenu du dépôt

```
Sony-Open-Gate-Lab/
├── cameras/             # 14 profils de boîtiers BIONZ XR (identité USB) + loader cameras.py
├── probe_a6700.py       # sonde diagnostic USB lecture seule
├── experiment_a6700.py  # écritures de session (opt-in, --confirm-session-write)
├── multi_exposure.py    # capture multi-exposition automatisée + empilement optionnel
├── monitor_hud.py       # HUD de monitoring/bascule rapide (guides de cadrage, waveform)
├── ram_opengate.py      # Open Gate RAM volatile (Mass Storage, recherche)
├── opengate_inject.py   # injecteur Open Gate mono-session (charge profiles/)
├── profiles/            # tables de patch Open Gate déclaratives (JSON) + README du format
├── sony_codes.py        # dictionnaires de codes PTP (constantes de protocole)
├── requirements.txt   # dépendances Python (pyusb ; pillow/numpy/OpenCV optionnels)
├── .gitignore         # exclusion stricte des binaires/firmware + dumps bruts
├── LICENSE            # licence MIT
├── RESEARCH.md        # découvertes matérielles inédites A6700 2.00
├── CONTRIBUTING.md / CONTRIBUTING.fr.md   # guide de contribution (EN / FR)
├── docs/
│   ├── PROTOCOL.md / PROTOCOL.en.md              # architecture protocole (FR / EN)
│   ├── DEVICE_PROPERTIES.md / .en.md             # table des 386 codes (FR / EN)
│   ├── RESULTS.md / RESULTS.en.md                # résultats expérimentaux en direct (FR / EN)
│   ├── ROADMAP.md / ROADMAP.en.md                # jalons & prochaines étapes (FR / EN)
│   └── proofs/                                   # extraits de logs anonymisés + captures de preuve
└── README.md / README.fr.md                      # ce fichier (EN / FR)
```

## 🖼️ Médias & échantillons

- **Avant / après :** _(captures à venir)_
- **Fichiers d'exemple :** _(lien Google Drive — à venir)_
- **Discord communautaire :** [Sony Alpha OpenLab](https://discord.gg/Zr72h6AFa5)

---

## 🙏 Remerciements

- **[ArcaneLantern/a6700-open-gate-test](https://github.com/ArcaneLantern/a6700-open-gate-test)**
  (GPL-3.0) — recherche Open Gate amont pour l'A6700. Son pipeline mode service et sa
  carte d'adresses ont servi de référence à notre voie RAM. *Référencé, jamais copié :*
  ce dépôt MIT ne contient aucune source GPL ni octet firmware ; nos profils ont été
  bâtis en clean-room depuis nos propres dumps matériels en lecture seule.
- **[ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)** (MIT) — le handshake
  mode service Sony.
- **Claude Code (Anthropic)** a fortement contribué à la recherche, à l'analyse de
  rétro-ingénierie et au développement de ce projet — analyse statique du firmware,
  cartographie du protocole PTP/SDIO et outillage Python.

---

## Licence

Distribué sous licence **MIT** (voir [LICENSE](LICENSE)). Code original uniquement ;
aucun composant ni fichier issu du firmware Sony.
