# Feuille de route — A6700-Remote-Tools

**🌍 Langue : [English](ROADMAP.en.md) · Français**

Une boîte à outils open-source pour les boîtiers Sony Alpha, développée et testée en
priorité sur le **Sony A6700**. Cette page suit ce qui fonctionne et la direction du
projet. Elle décrit **uniquement des capacités et des objectifs** — aucun détail
propriétaire du firmware.

> Rappel de périmètre : la recherche se limite à l'**Open Gate 3:2** et à la
> **multi-exposition**, **sans aucune modification permanente** du boîtier. Lecture
> seule par défaut ; toute écriture est opt-in et de session uniquement (effacée au
> redémarrage / retrait de batterie).

---

## ✅ Accompli

- **Sonde USB PTP / « SDIO »** (`probe_a6700.py`) — strictement en lecture seule :
  ouverture de session, lecture des informations device, énumération des propriétés
  et codes de contrôle exposés, décodage des valeurs courantes et autorisées. Validé
  en direct sur l'A6700 (firmware 2.00).
- **Contrôle de prise de vue** (`experiment_a6700.py`) — session uniquement :
  demi-pression (AF), pleine pression (obturateur) et démarrage/arrêt vidéo par USB,
  tous confirmés fonctionnels.
- **Multi-exposition automatisée** (`multi_exposure.py`) — capture de N vues à
  intervalle contrôlé, avec téléchargement d'images optionnel en lecture seule et
  empilement local (average, lighten, screen).
- **Expérience double exposition native** — mode interactif pas-à-pas et fenêtre
  d'aperçu Live View superposé en temps réel (aligner la Vue 2 sur la Vue 1, Espace
  pour déclencher, fusion instantanée), reproduisant le flux natif Fujifilm/Canon.
- **Documentation de référence** — vue d'ensemble du protocole, dictionnaire des
  codes de propriété et de contrôle, et page de résultats expérimentaux, le tout
  bilingue (EN/FR).
- **Modèle de sécurité** — conception lecture seule par défaut, avec garde-fou
  explicite pour toute écriture de session, et interdiction stricte de diffuser du
  contenu de firmware.

---

## 🔭 Prochaines étapes

### 1. Portabilité (mobile / embarqué)
- Empaqueter la boîte à outils pour un usage au-delà du bureau : un petit hôte
  embarqué (ex. carte monocarte) et, à terme, un compagnon mobile.
- Conserver une séparation propre transport/UI pour qu'un même cœur alimente les
  interfaces CLI, embarquée et mobile.

### 2. Open Gate 3:2 — étude du canal mémoire volatile (RAM-only)
- Nos tests en direct montrent que la bascule vidéo 3:2 est bloquée au-dessus du
  protocole USB, au niveau applicatif. Une simple écriture de propriété est acceptée
  mais ignorée.
- Prochaine étape : étudier un **canal mémoire volatile, de session uniquement**
  (rien écrit en mémoire persistante ni dans le firmware ; changements effacés au
  redémarrage) pour comprendre où ce verrou est appliqué, strictement à des fins de
  recherche.
- Cela reste exploratoire et n'est mené que dans le cadre de la politique « aucune
  écriture permanente ».

### 3. Autres boîtiers Sony Alpha
- **BIONZ XR APS-C** d'abord (les plus proches de l'A6700) : ex. FX30.
- **BIONZ XR Full-Frame** ensuite : ex. A7 IV, A7C II.
- **BIONZ X** par la suite (dialecte de protocole plus ancien) : ex. A6400, A6600.
- Aide de la communauté bienvenue pour valider PID, jeux de propriétés et codes de
  contrôle par boîtier.

---

## 🤝 Comment aider

Ouvrez une [GitHub Issue](../../issues) ou une [Discussion](../../discussions) avec
votre boîtier, la version de firmware et ce que vous aimeriez voir (une
fonctionnalité, ou le support de votre appareil). Un Discord communautaire est prévu.
Voir [`CONTRIBUTING.fr.md`](../CONTRIBUTING.fr.md).

*Les jalons sont indicatifs et peuvent évoluer au fil des tests.*
