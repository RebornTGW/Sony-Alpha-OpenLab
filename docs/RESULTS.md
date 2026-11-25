# Résultats expérimentaux — Sony A6700

**🌍 Langue : [English](RESULTS.en.md) · Français**

Validé en direct sur un **Sony A6700 (ILCE-6700)**, firmware **2.00**, mode USB **PC
Remote** (PID **`0x0E78`**, VID `0x054C`), via PTP / Sony « SDIO ». Constantes de
protocole uniquement ; aucun fichier de firmware n'est inclus dans ce dépôt.

## Bilan

| Objectif | Statut | Preuve |
|---|---|---|
| **Multi-exposition (capture pilotée)** | ✅ **Fonctionnel** | Contrôle USB complet de la capture multi-vues via `ControlDevice(0x9207)` S1/S2 ; `multi_exposure.py` l'automatise. |
| **Open Gate 3:2 (vidéo)** | 🔒 **Bloqué (couche applicative)** | `SetExtDevicePropValue(0xD211)=3:2` renvoie `OK` mais est ignoré ; HAITA maintient 16:9 en Vidéo. |

---

## 1. Multi-exposition — succès complet

La chaîne de capture du boîtier est entièrement pilotable par USB, d'abord en
diagnostic lecture seule, puis en contrôle de session :

- **Handshake de session** (`probe_a6700.py`) : `OpenSession(0x1002)` → `SDIO_Connect
  (0x9201)` ph1/ph2/ph3 (chacune `OK`, DATA 8 octets) → `SDIO_GetExtDeviceInfo
  (0x9202)` (~826 octets) → `GetAllExtDevicePropInfo(0x9209)` (~8019 octets, 122
  propriétés actives en mode Vidéo).
- **Contrôle du déclenchement** (`experiment_a6700.py`, `multi_exposure.py`) :
  `ControlDevice(0x9207)` sur **S1 `0xD2C1`** (demi-pression / AF), **S2 `0xD2C2`**
  (pleine pression / obturateur) et **`0xD2C8`** (enregistrement vidéo) — tous
  renvoient `OK`. Valeurs : press = `2`, release = `1`.
- **Automatisation** (`multi_exposure.py`) : réglage drive/bracket optionnel via
  `still_capture_mode (0x5013)`, puis N vues à intervalle contrôlé, avec
  téléchargement PTP lecture seule optionnel des nouvelles vues et empilement local
  (`average` = fusion multi-exposition, `lighten` = filé d'étoiles).

**Conclusion :** l'objectif multi-exposition est atteint **sans aucune modification
permanente** du boîtier — tout est contrôle de session + traitement d'image local.

```powershell
python multi_exposure.py --confirm-session-write --shots 8 --interval 0.8 \
    --download-dir out/ --stack out/multi.png --stack-mode average
```

---

## 2. Open Gate 3:2 — verrou applicatif confirmé

`aspect_ratio (0xD211)` est une propriété `Get/Set`, `enabled=1`. Valeurs courantes
observées : **`1` (3:2) en mode Photo**, **`2` (16:9) en mode Vidéo**.

Expérience (`experiment_a6700.py --test-aspect-3-2`, en mode Vidéo) :

1. lecture de `0xD211` via le flux `0x9209` → `2` (16:9) ;
2. `SetExtDevicePropValue(0x9205)` écriture `1` (3:2) → **réponse `0x2001 OK`** ;
3. relecture de `0xD211` via `0x9209` → **toujours `2` (16:9)**.

L'écriture est **acceptée puis silencieusement ignorée**. Cela confirme
expérimentalement la trouvaille d'analyse statique : le **HAITA Feature Manager**
impose `REC_MOVIE_ASPECT_RATIO_NOT_16_9` pour l'enregistrement film dans `appFw.so`,
**au-dessus** de la couche PTP. Le jeu de propriétés PTP expose le 3:2, mais le verrou
applicatif le neutralise en mode Vidéo.

**Conclusion :** l'Open Gate 3:2 vidéo **n'est pas atteignable par une écriture de
propriété PTP**. Toute suite devrait agir sur le verrou applicatif lui-même (voir le
plan d'investigation RAM-only dans les notes du projet), ce qui sort du périmètre
« session uniquement, sans écriture permanente » de ce dépôt.

---

*Reproduisez les diagnostics avec `probe_a6700.py` (lecture seule). Les écritures sont
opt-in et de session uniquement via `experiment_a6700.py` / `multi_exposure.py`.*
