# Sony-Alpha-OpenLab

**🌍 Langue : [English](README.md) · Français**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
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
- **Multi-exposition :** `multi_exposure.py` capture + fusion (`average`/`lighten`/
  `screen`) fonctionnel de bout en bout.
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
vendor Sony « SDIO »), largement partagé dans la gamme. Le support est déployé par
génération de processeur :

| Génération | Boîtiers | Support prévu |
|---|---|---|
| **BIONZ XR** (APS-C) | **A6700** ✅, **FX30**, **ZV-E10 II** | **Direct / prioritaire** — cible de développement principale |
| **BIONZ XR** (Full-Frame) | A7 IV, A7C II, … | Direct (après validation APS-C) |
| **BIONZ X** (APS-C) | A6600, A6400 | Support ultérieur (dialecte de protocole plus ancien) |

Priorité de développement :

1. **Sony A6700** — boîtier de référence (développé et testé ici en premier).
2. Autres boîtiers **BIONZ XR APS-C** (FX30, ZV-E10 II) — compatibilité directe attendue.
3. **Full-Frame BIONZ XR** (A7 IV, A7C II…).
4. Boîtiers **BIONZ X** (A6400, A6600) — traités ensuite, leur génération de
   protocole étant différente.

**Profils par boîtier** dans [`cameras/`](cameras/) (architecture modulaire Sony
APS-C BIONZ XR) : **`a6700`** (principal), **`fx30`**, **`zve10m2`** — même capteur
26 MP APS-C BIONZ XR. Chargement via `from cameras import load_profile`. Les boîtiers
**BIONZ X** (A6400, A6600, ZV-E10 Mark I) viendront ensuite ; **ZV-E1 = Full-Frame**
(à part).

> ✅ = activement testé · autres = prévus. La compatibilité est validée boîtier par
> boîtier ; la présence d'un code dans le protocole ne signifie pas qu'il est exposé
> sur tous les modèles. Vous voulez votre boîtier pris en charge ? Voir
> [Communauté & idées](#-communauté--idées).

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

> ⚠️ **Un pilote WinUSB par mode USB.** Le boîtier expose un **PID USB différent selon
> le mode** — **PC Remote `0x0E78`** vs **Mass Storage `0x0E76`** (utilisé par
> `ram_opengate.py`). Windows traite chaque PID comme un périphérique distinct : il
> faut donc relancer Zadig et lier **WinUSB** à nouveau après avoir changé de mode.
> Pour annuler une liaison : *Gestionnaire de périphériques → l'interface →
> Désinstaller le périphérique* → débrancher/rebrancher.

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
intervalle contrôlé** et peut éventuellement les **empiler** localement (average =
fusion multi-exposition classique, ou lighten = filé d'étoiles). Il exige aussi
`--confirm-session-write` et prend de vraies photos.

```powershell
# 5 vues, 1 s d'intervalle (AF avant chaque prise)
python multi_exposure.py --confirm-session-write --shots 5 --interval 1.0

# Mode drive continu/bracket, sans AF, téléchargement auto de chaque vue (0xFFFFC001)
# et empilement en une seule image de multi-exposition
python multi_exposure.py --confirm-session-write --shots 8 --no-af --drive-value 0x2 \
    --download-dir out/ --stack out/multi.png --stack-mode average

# HORS-LIGNE : empiler un dossier (sans boîtier, sans --confirm-session-write)
python multi_exposure.py --stack-dir ./frames --stack trails.png --stack-mode lighten

# Double exposition interactive : Vue 1, recadrage, Entrée pour la Vue 2, fusion auto
python multi_exposure.py --confirm-session-write --interactive --shots 2 \
    --download-dir out/ --stack out/double.png --stack-mode screen

# Aperçu Live View superposé en temps réel (aligner la Vue 2 ; Espace = déclencher)
python multi_exposure.py --confirm-session-write --live-overlay --shots 2 \
    --download-dir out/ --stack out/double.png --stack-mode screen --overlay-opacity 0.5
```

| Option | Rôle |
|---|---|
| `--shots N` / `--interval S` | capture N vues, espacées de S secondes |
| `--no-af` | saute le demi-appui S1 (AF) ; S2 pleine pression seulement |
| `--drive-value V` | règle `still_capture_mode` (0x5013) d'abord (valeur d'énum continu/bracket) |
| `--download-dir DIR` | télécharge auto chaque vue via le handle Sony `0xFFFFC001` (`GetObject`, lecture seule) |
| `--stack OUT` / `--stack-dir DIR` / `--stack-mode` | empile les images : `average`, `lighten` ou `screen` |
| `--interactive` | pas-à-pas : Vue 1, pause pour recadrer, Entrée pour chaque vue suivante, puis fusion |
| `--live-overlay` / `--overlay-opacity` | fenêtre live superposant le flux (`0xFFFFC002`) sur la Vue 1 ; Espace déclenche |

**Expérience double exposition native.** `--live-overlay` reproduit le flux natif
Fujifilm/Canon : prendre la Vue 1, voir le Live View superposé en temps réel pour
aligner la Vue 2, appuyer sur **Espace** pour déclencher, et la fusion finale est
générée instantanément. `screen` (`1-(1-A)(1-B)`) est la fusion double-exposition
classique ; `lighten` garde les pixels les plus clairs. La fenêtre utilise `tkinter`
(fourni avec Python) + Pillow — aucune dépendance supplémentaire.

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

---

## 🧬 Open Gate RAM volatile (recherche, `ram_opengate.py`)

Séparé des outils PC Remote. Utilise le canal service **USB Mass Storage** (commandes
SCSI vendor, style updater Sony ouvert / PMCA-RE) — **A6700 MSC `PID 0x0E76`**. Tout
effet est en RAM : **effacé à l'extinction / retrait batterie**.

> **Basculez le mode USB du boîtier sur _Mass Storage_** (pas PC Remote) pour cet outil.

```bash
# Lecture seule (défaut) : trouve libmpr.so en RAM, vérifie les octets stock 3840x2160
python ram_opengate.py --verify-only

# Patch volatile opt-in (#0x870 2160 -> #0xa00 2560), sauvegarde d'abord
python ram_opengate.py --confirm-ram-write

# Revert en RAM sans redémarrer
python ram_opengate.py --restore
```

> ⚠️ **Recherche.** `ram_opengate.py` = code MIT original uniquement ; les CDB mémoire
> vendor Sony sont des constantes à confirmer sur boîtier (aucun octet firmware, aucun
> code GPL). `--verify-only` n'écrit rien. L'Open Gate est verrouillé au niveau
> applicatif (HAITA) ; cet outil vise le mot encodeur aval en RAM. À vos risques.

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
Sony-Alpha-OpenLab/
├── cameras/             # profils par boîtier (a6700, fx30, zve10m2) + loader cameras.py
├── probe_a6700.py       # sonde diagnostic USB lecture seule
├── experiment_a6700.py  # écritures de session (opt-in, --confirm-session-write)
├── multi_exposure.py    # capture multi-exposition automatisée + empilement optionnel
├── ram_opengate.py      # Open Gate RAM volatile (Mass Storage, recherche)
├── sony_codes.py        # dictionnaires de codes PTP (constantes de protocole)
├── requirements.txt   # dépendances Python (pyusb ; pillow/numpy optionnels)
├── .gitignore         # exclusion stricte des binaires/firmware
├── LICENSE            # licence MIT
├── CONTRIBUTING.md / CONTRIBUTING.fr.md   # guide de contribution (EN / FR)
├── docs/
│   ├── PROTOCOL.md / PROTOCOL.en.md              # architecture protocole (FR / EN)
│   ├── DEVICE_PROPERTIES.md / .en.md             # table des 386 codes (FR / EN)
│   ├── RESULTS.md / RESULTS.en.md                # résultats expérimentaux en direct (FR / EN)
│   └── ROADMAP.md / ROADMAP.en.md                # jalons & prochaines étapes (FR / EN)
└── README.md / README.fr.md                      # ce fichier (EN / FR)
```

## 🖼️ Médias & échantillons

- **Avant / après :** _(captures à venir)_
- **Fichiers d'exemple :** _(lien Google Drive — à venir)_
- **Discord communautaire :** [Sony Alpha OpenLab](https://discord.gg/Zr72h6AFa5)

---

## 🙏 Remerciements

**Claude Code (Anthropic)** a fortement contribué à la recherche, à l'analyse de
rétro-ingénierie et au développement de ce projet — analyse statique du firmware,
cartographie du protocole PTP/SDIO et outillage Python.

---

## Licence

Distribué sous licence **MIT** (voir [LICENSE](LICENSE)). Code original uniquement ;
aucun composant ni fichier issu du firmware Sony.
