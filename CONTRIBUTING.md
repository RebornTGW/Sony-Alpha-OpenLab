# Guide de contribution — A6700-Remote-Tools

Merci de votre intérêt ! Ce projet documente et teste le protocole de contrôle à
distance du Sony A6700 à des fins **d'interopérabilité et d'étude**. Quelques règles
simples garantissent qu'il reste propre, sûr et partageable publiquement.

## 🔒 Règle n°1 — Aucun contenu de firmware

**Ne commitez jamais** de fichier issu du firmware Sony ni de donnée binaire
propriétaire, notamment :

- firmware et bibliothèques : `*.so`, `*.bin`, `*.DAT`, `*.ko`, `*.elf`, `*.img` ;
- firmwares décompressés, dumps, images partition, extraits de `.rodata`/`.data` ;
- toute copie de code désassemblé reproduisant du code Sony.

Le `.gitignore` bloque déjà ces extensions, mais la vigilance reste de votre
ressort. Ce qui est autorisé : les **constantes de protocole** (opcodes, codes de
propriété, noms symboliques) et la **documentation** décrivant le protocole — ce
sont des faits d'interopérabilité, pas du code redistribué.

## 🛡️ Règle n°2 — Priorité à la lecture seule

L'outil de référence (`probe_a6700.py`) est **strictement en lecture seule** et le
reste par défaut. Toute contribution introduisant une opération d'écriture ou de
contrôle (`SetExtDevicePropValue` 0x9205, `ControlDevice` 0x9207, `SendObject`,
formatage, mise à jour firmware…) doit :

1. être **désactivée par défaut** et protégée par un drapeau explicite
   (ex. `--enable-write`) avec confirmation ;
2. ne jamais être ajoutée à la liste blanche `READ_ONLY_OPS` ;
3. documenter clairement l'effet matériel sur le boîtier.

Rappel : S1/S2/Movie Rec et toute action `ControlDevice` modifient l'état physique
du boîtier (déclenchement, enregistrement). Traitez-les avec prudence.

## 🧪 Règle n°3 — Tests responsables

- Testez sur **votre propre matériel**, batterie chargée, sans carte contenant des
  données importantes.
- Préférez le mode `--no-sdio` pour un premier contact.
- Signalez dans vos PR le modèle, la version de firmware et l'OS utilisés.

## 🔧 Mise en place de l'environnement

```bash
python -m venv .venv
# Windows : .\.venv\Scripts\activate   |   Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
```

Sous Windows, installez le pilote WinUSB sur l'interface PTP du boîtier via Zadig
(voir [README.md](README.md)).

## 📐 Style de code

- Python 3.9+, conforme **PEP 8** ; largeur de ligne ~100 colonnes.
- Noms explicites ; docstrings en tête de module et de fonction publique.
- Les constantes de protocole (opcodes, codes) sont regroupées et nommées.
- Évitez les dépendances superflues : le cœur ne doit dépendre que de `pyusb`.

## 🔀 Processus de PR

1. Forkez et créez une branche : `git checkout -b feat/ma-fonction`.
2. Un commit = une intention. Messages à l'impératif, en anglais ou français
   cohérent (ex. `add GetExtDeviceInfo parser`).
3. Vérifiez : `python -c "import ast; ast.parse(open('probe_a6700.py').read())"`
   et, si possible, un test réel en lecture seule.
4. Confirmez qu'**aucun binaire** n'est ajouté : `git status` + `git ls-files`.
5. Ouvrez la PR en décrivant le comportement et l'impact éventuel sur le boîtier.

## 📄 Licence

En contribuant, vous acceptez que votre contribution soit distribuée sous licence
**MIT** (voir [LICENSE](LICENSE)).
