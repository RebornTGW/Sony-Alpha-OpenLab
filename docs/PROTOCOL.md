# Protocole de contrôle à distance PTP / « SDIO » — Sony A6700 (ILCE-6700)

Description technique du protocole de communication entre un hôte (PC / smartphone)
et le boîtier **Sony A6700**, telle que reconstituée par **analyse statique
indépendante**. Document de référence pour `probe_a6700.py`.

> Ce document ne contient aucun fichier ni extrait du firmware Sony. Les opcodes et
> codes de propriété sont des **constantes de protocole** (PTP / ISO 15740 et
> l'espace vendor Sony), utilisées à des fins d'interopérabilité.

---

## 1. Pile de transport

Le boîtier expose, côté USB, une interface **Still Image / PTP** (classe USB `0x06`)
lorsqu'il est réglé sur le mode de connexion **PC Remote** (ou **PTP**). Le même
protocole applicatif est transporté sur deux canaux :

| Canal | Transport | Usage |
|---|---|---|
| **USB** | PTP sur bulk-in / bulk-out (classe Still Image) | connexion filaire PC Remote |
| **Réseau (PTP/IP)** | sockets TCP, multi-sessions, appairage | Wi-Fi / Imaging Edge |

`probe_a6700.py` n'implémente que le canal **USB**.

### Conteneur PTP/USB

Chaque message est un conteneur de 12 octets d'en-tête + charge utile :

```
offset 0  : uint32  length      (longueur totale, en-tête inclus)
offset 4  : uint16  type        1=Command, 2=Data, 3=Response, 4=Event
offset 6  : uint16  code        opcode (Command) ou response code (Response)
offset 8  : uint32  transaction_id
offset 12 : charge utile        paramètres (Command) ou données (Data)
```

Une transaction = **phase Commande** (hôte → boîtier) → **phase Données**
optionnelle → **phase Réponse** (boîtier → hôte, `response_code`, `0x2001` = OK).
Le découpage en 3 phases se retrouve côté firmware dans les handlers
`cmd_* / dat_* / res_*`.

---

## 2. Architecture logicielle (côté boîtier)

La chaîne de contrôle distant est **stratifiée** :

```
 Application (menus, capacités modèle)
      │
      ▼
 Couche vendor « Camera Remote »   ── opérations MrpwSDIO* (0x92xx)
      │                                liveview, transfert, propriétés étendues
      ▼
 Registre de plug-ins / opcodes    ── handlers enregistrés par code d'opération
      │
      ▼
 Moteur PTP de base                ── table d'opérations + 3 phases cmd/dat/res
      │                                opérations standard 0x10xx
      ▼
 Transports                        ── USB (Still Image bulk) / PTP-IP (socket)
```

- Les **opérations standard** (0x1001–0x101B) sont le socle PTP : session, device
  info, énumération et transfert d'objets.
- Les **opérations vendor Sony « SDIO »** (à partir de `0x9201`) ajoutent la
  découverte de capacités étendues, la lecture/écriture de propriétés de prise de
  vue, le déclenchement, le liveview, le transfert FTP/HTTP, etc.
- Les **commandes d'extension** sont encapsulées dans deux opérations vendor
  dédiées : `0x9280` (*Send Ext Command*) et `0x9281` (*Get Ext Response*).

---

## 3. Opérations (opcodes)

### 3.1 Standard PTP (ISO 15740)

| Opcode | Opération | Accès |
|---|---|---|
| 0x1001 | GetDeviceInfo | lecture |
| 0x1002 | OpenSession | session |
| 0x1003 | CloseSession | session |
| 0x1004 | GetStorageIDs | lecture |
| 0x1005 | GetStorageInfo | lecture |
| 0x1006 | GetNumObjects | lecture |
| 0x1007 | GetObjectHandles | lecture |
| 0x1008 | GetObjectInfo | lecture |
| 0x1009 | GetObject | lecture |
| 0x100A | GetThumb | lecture |
| 0x100D | SendObject | **écriture** |
| 0x101B | GetPartialObject | lecture |

### 3.2 Vendor Sony « SDIO » (extrait)

Espace d'opcodes contigu à partir de `0x9201`. Les opérations en **gras** sont
utilisées (lecture seule) par `probe_a6700.py` ; celles marquées *(écriture)* ne le
sont jamais.

| Opcode | Opération | Rôle |
|---|---|---|
| **0x9201** | `Connect` | handshake de session vendor |
| **0x9202** | `GetExtDeviceInfo` | capacités remote |
| **0x9203** | `GetExtDevicePropDesc` | descripteur d'une propriété |
| 0x9204 | `GetExtDevicePropValue` | valeur d'une propriété (lecture) |
| 0x9205 | `SetExtDevicePropValue` | écriture d'une propriété *(écriture)* |
| 0x9206 | `GetControlDeviceDesc` | descripteur des codes de contrôle |
| 0x9207 | `ControlDevice` | actionnement / déclenchement *(écriture)* |
| 0x9208 | `GetAllExtDeviceProp` | dump valeurs de toutes les propriétés |
| 0x9209 | `GetAllExtDevicePropInfo` | dump descripteurs de toutes les propriétés |
| 0x920A | `GetCautionInfo` | messages / avertissements |
| 0x9210 | `OpenSession` (SDIO) | session vendor |
| 0x9211 | `GetPartialLargeObject` | transfert partiel gros objets |
| 0x9213 | `GetDeviceLog` | journaux |
| 0x9214 | `SetRemoteSdkInfo` | identification du SDK hôte |
| 0x9216 | `GetVenderCodeVersion` | version du code vendor |
| 0x921A | `UploadData` | envoi hôte → boîtier *(écriture)* |
| 0x921D | `DownloadData` | réception boîtier → hôte |
| 0x9238 | `GetOSDImage` | image OSD liveview |
| … | (espace jusqu'à ~0x923A) | FTP, presets, firmware, synchro, etc. |
| 0x9280 | *Send Ext Command* | transport commande d'extension *(écriture)* |
| 0x9281 | *Get Ext Response* | transport réponse d'extension |

---

## 4. Propriétés (`DevicePropCode`)

Le dialogue de prise de vue est **générique et piloté par les données** : l'hôte
transmet un `DevicePropCode` (uint16) en paramètre d'une opération
`GetExtDevicePropDesc / Value` ou `SetExtDevicePropValue`. Le descripteur renvoyé
indique le type, l'accès (lecture seule / lecture-écriture) et la plage de valeurs.

Plages :

| Plage | Nature |
|---|---|
| 0x50xx | propriétés standard PTP |
| 0xD1xx | propriétés vendor Sony (réglages, statuts) |
| 0xD2xx | propriétés vendor Sony (réglages + « boutons » 0xD2Cx–0xD2Fx) |
| 0xD3xx | codes de contrôle système (`ControlDevice`) |

La liste exhaustive (**386 codes**) et leurs noms symboliques se trouvent dans
[`DEVICE_PROPERTIES.md`](DEVICE_PROPERTIES.md).

### Codes de référence

| Code | Nom | Note |
|---|---|---|
| `0x5013` | `still_capture_mode` | mode Drive : single / continu / retardateur / **bracket** |
| `0xD211` | `aspect_ratio` | 3:2 / 16:9 / 4:3 / 1:1 (film verrouillé 16:9 par capacité modèle) |
| `0xD241` | `file_format_movie` | XAVC HS / S / S-I |
| `0xD242` | `recording_setting_movie` | résolution / débit |
| `0xD286` | `recording_frame_rate_setting_movie` | cadence film |
| `0xD20D` / `0xD21E` | `shutter_speed` / `iso_sensitivity` | exposition |

### Déclenchement (⚠️ écriture — jamais émis par cet outil)

Le déclenchement n'est **pas** une écriture de propriété classique mais passe par
`ControlDevice` (0x9207) sur des codes « boutons » :

| Code | Nom | Effet |
|---|---|---|
| `0xD2C1` | `s1_button` | demi-pression (AF) |
| `0xD2C2` | `s2_button` | pression complète (déclenchement photo) |
| `0xD2E6` | `s1_and_s2_button` | S1 + S2 |
| `0xD2C8` | `movie_rec_button` | enregistrement vidéo start/stop |

---

## 5. Séquence de dialogue type (USB)

```
OpenSession(0x1002)
  └─ Connect(0x9201)                 handshake session vendor
       └─ SetRemoteSdkInfo(0x9214)   identification de l'hôte
            └─ GetExtDeviceInfo(0x9202) / GetAllExtDevicePropInfo(0x9209)
                 └─ GetExtDevicePropDesc(0x9203, prop=0x5013/0xD211/0xD241…)   [lecture]
                      └─ (optionnel, écriture) SetExtDevicePropValue(0x9205, …)
                           └─ (optionnel, écriture) ControlDevice(0x9207, S1→S2)
                                └─ GetObject / GetPartialLargeObject
CloseSession(0x1003)
```

`probe_a6700.py` s'arrête aux étapes **de lecture** (jusqu'à `GetExtDevicePropDesc`),
puis ferme la session.

---

## 6. Méthodologie d'extraction

Les informations ci-dessus proviennent d'une analyse statique (désassemblage
AArch64, inspection ELF) des bibliothèques applicatives du boîtier :

- correspondance **opcode ↔ opération** : tables de fabrique
  `Mrpw*EntryManager::makeInstance` (chargement de vtable via la GOT) ;
- correspondance **code ↔ nom de propriété** : table de registration des propriétés
  distantes (chaîne de nom chargée juste avant l'affectation du code) ;
- transport des commandes d'extension : aiguillage `0x9280` / `0x9281` dans le
  dispatcher de commandes d'extension.

Aucune donnée binaire du firmware n'est reproduite ni redistribuée dans ce dépôt.
