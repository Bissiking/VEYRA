# INSTALLATION — VEYRA V0.2

## 1. macOS (plateforme prioritaire)

### Prérequis

- macOS 13 (Ventura) ou supérieur (non testé sur versions antérieures).
- Python **3.12+** (recommandé : [python.org](https://www.python.org/downloads/),
  vérifier avec `python3 --version`).
- Une webcam intégrée ou USB.
- Aucun droit administrateur requis.
- ~150 Mo : environnement virtuel + modèles ONNX (38 Mo).

### Installation

```bash
git clone <url-du-depot> VEYRA
cd VEYRA

# 1. Environnement virtuel + dépendances
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. Modèles biométriques locaux (YuNet + SFace, SHA-256 vérifié)
python scripts/download_models.py

# 3. Lancement (mode SIMULATION par défaut)
python -m veyra
# ou, en développement :
./scripts/run_dev.sh
```

### Première utilisation

1. Au lancement : badge **SIMULATION** en bas de la barre latérale.
2. **Réglages > Caméra** : index de caméra (0 par défaut), appliquer.
3. **Présence > Enrôler mon visage** : suivre les invites
   (varier les angles — 8 échantillons).
4. **Autorisations macOS** : la première ouverture de caméra déclenche la
   demande système ; pour l'activité clavier/souris, accorder
   *Réglages > Confidentialité et sécurité > Accessibilité* **et**
   *Surveillance des événements*, puis redémarrer le module dans la page Modules.
   Sans ces autorisations, `activity_guard` affiche `DEGRADED` — VEYRA reste
   utilisable mais la détection d'activité est absente (jamais simulée).
5. Observer la page **Événements** : les décisions et verrouillages simulés
   y apparaissent.

### Verrouillage réel (mode PROTECTION) — avant de l'activer

- Le verrouillage utilise `osascript` (raccourci Ctrl+Cmd+Q) et nécessite
  l'autorisation **Accessibilité** pour l'application (sinon le verrouillage
  échoue et l'échec est journalisé).
- N'activer la PROTECTION qu'après avoir validé les scénarios en simulation
  (voir `docs/SIMULATION.md` § Manuel).

### Vérification de l'installation

```bash
# Tests unitaires (135 tests, aucune caméra requise)
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# Version
python -m veyra --version
```

### Désinstallation

```bash
rm -rf .venv models
rm -rf ~/Library/Application\ Support/VEYRA   # base + logs
security delete-generic-password -s veyra.biometric -a profile_kek  # clé biométrique
```

### Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `face_guard` en ERROR « modèle(s) manquant(s) » | modèles absents | `python scripts/download_models.py` |
| Aperçu « Caméra indisponible » | permission ou caméra occupée | *Confidentialité > Caméra* ; fermer les autres apps caméra |
| `activity_guard` en DEGRADED | Accessibilité/Surveillance non accordées | accorder puis redémarrer le module (page Modules) |
| Verrouillage PROTECTION « échoué » | Accessibilité non accordée à l'app | accorder l'autorisation |
| Interface lente / CPU élevé | cadence d'analyse trop élevée pour la machine | activer `low_power` (Réglages > Performances) |
| `pynput` plante au lancement | sandbox/tcc | lancer hors sandbox ; vérifier les autorisations |
| Base SQLite verrouillée | instance VEYRA déjà ouverte | vérifier le tray, « Quitter complètement » |

## 2. Windows

Install :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/download_models.py
python -m veyra
```

Capacités Windows (V0.2) :

- **Verrouillage** : `LockWorkStation` (fonction native, pas de permission
  requise).
- **Coffre clés** : DPAPI utilisateur (`CryptProtectData`) — enrôlement
  biométrique disponible.
- **Activité clavier/souris** : non implémentée (`UNAVAILABLE`, visible en GUI).

> **Non validé sur matériel Windows** : les capacités sont implémentées et
> testées par tests unitaires, mais pas expérimentées sur un PC réel.

## 3. Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/download_models.py
python -m veyra
```

Prérequis optionnels :

- `loginctl` (systemd) : requis pour le verrouillage réel.
- `secret-tool` (libsecret) : requis pour le coffre clés (enrôlement).
  Absents → capacités `False` affichées, enrôlement refusé explicitement.

Capacités Linux (V0.2) :

- **Verrouillage** : `loginctl lock-session` (si présent).
- **Coffre clés** : Secret Service via `secret-tool` (si présent).
- **Activité clavier/souris** : non implémentée (`UNAVAILABLE`, visible en GUI).

> **Non validé sur matériel Linux** : idem Windows — implémenté et testé
> unitairement, pas expérimenté sur un poste réel.

## 4. Note de compatibilité

| Fonction | macOS | Windows | Linux |
|---|---|---|---|
| GUI PySide6 | ✅ | ⚠️ non testée | ⚠️ non testée |
| Détection/reconnaissance faciale | ✅ | ✅ théorique* | ✅ théorique* |
| Enrôlement (coffre clés) | ✅ Keychain | ✅ DPAPI | ✅ Secret Service† |
| Activité clavier/souris | ✅ (permissions) | ❌ non implémenté | ❌ non implémenté |
| Verrouillage réel | ✅ (permission) | ✅ LockWorkStation | ✅ loginctl† |

\* le pipeline OpenCV/ONNX Runtime est multiplateforme mais n'a été validé
expérimentalement que sur macOS.
† nécessite l'outil système correspondant ; sinon la capacité est `False`
et l'enrôlement est refusé explicitement.
