# VEYRA

**Plateforme de sécurité locale, modulaire et adaptative.**  
Reconnaissance faciale et décision 100 % hors ligne, surveillance d'activité
sans contenu, verrouillage de session piloté par un moteur adaptatif — avec un
**coupe-circuit SIMULATION** actif par défaut.

> **Statut : V0.2 — anti-spoofing, calibration, multiplateforme.**  
> Plateformes supportées : **macOS** (prioritaire), **Windows**, **Linux**
> (verrouillage + coffre clés ; activité clavier/souris macOS seule — voir
> [INSTALLATION](docs/INSTALLATION.md#4-note-de-compatibilité)).

## Principe

- **Aucun cloud, aucune donnée sortante** : tout tourne en local, sans droits
  administrateur (sous réserve des autorisations accordées par le système).
- **Un seul point de verrouillage** : les modules observent, le moteur décide,
  un exécuteur unique agit — et **n'agit jamais en mode SIMULATION**.
- **Transparence** : chaque fonctionnalité est documentée avec son état réel
  (implémenté / expérimental / planifié). Rien n'est simulé silencieusement.

## Fonctionnalités (V0.2)

| Domaine | Implémenté |
|---|---|
| Présence faciale | détection YuNet, empreinte SFace (ONNX Runtime), enrôlement multi-angles chiffré (coffre clés système), 4 états, multi-visages, suppression complète du profil |
| Anti-spoofing | détection clignement + score texture locale, dégradation TRUSTED→UNKNOWN si suspect (heuristiques, limites documentées) |
| Calibration | courbe FAR/FRR locale, seuil EER applicable depuis les Réglages — aucune donnée biométrique sortante |
| Surveillance adaptative | mode léger après 10 s d'inactivité, analyse espacée de 5 s, confirmation d'identité suspecte sur 2 s, analyse prioritaire à la reprise |
| Décision | inconnu confirmé + activité → verrouillage ; absence sans activité → maintien ; webcam perdue après absence + activité → verrouillage selon politique |
| Coupe-circuit | SIMULATION par défaut à chaque démarrage, PROTECTION avec confirmation explicite, exécuteur unique, journalisation complète |
| Plateformes | verrouillage macOS / Windows / Linux ; coffre clés Keychain / DPAPI / Secret Service ; démarrage au login (optionnel) |
| Activité | clavier/souris **sans enregistrement de contenu** (horodatages seuls, macOS) |
| Interface | PySide6 sombre, 5 pages (Dashboard, Présence, Modules, Événements, Réglages), icône de tray, fermeture masquante, sortie explicite |
| Tests | 135 tests (moteur, coupe-circuit, scénarios d'intrusion sans webcam, liveness, calibration, plateformes, smoke GUI) |

Limites assumées (notamment **anti-usurpation**) : [SECURITY.md](docs/SECURITY.md).

## Démarrage rapide (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/download_models.py   # modèles ONNX locaux (SHA-256 vérifié)
python -m veyra                     # ou : ./scripts/run_dev.sh
```

Installation détaillée et dépannage : **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.

### Commandes utiles

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q   # lancer les tests
python -m veyra --version                               # version
python -m veyra --verbose                               # journaux DEBUG
./scripts/run_dev.sh                                    # lancement développement
python scripts/download_models.py                       # (ré)obtenir les modèles
```

## Documentation

| Document | Contenu |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | composants, flux de données, threads, cycle de vie |
| [docs/MODULES.md](docs/MODULES.md) | fonctionnement des modules, interface, guide de création |
| [docs/SECURITY.md](docs/SECURITY.md) | modèle de menace, biométrie chiffrée, **limites anti-usurpation**, permissions macOS |
| [docs/DETECTION.md](docs/DETECTION.md) | reconnaissance faciale, surveillance adaptative, règles du moteur |
| [docs/SIMULATION.md](docs/SIMULATION.md) | coupe-circuit, modes, scénarios de test |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | paramètres et valeurs par défaut |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | installation macOS + compatibilité Windows/Linux |
| [docs/ROADMAP.md](docs/ROADMAP.md) | état réel des fonctionnalités et évolutions prévues |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | historique des modifications |

## Structure

```
veyra/        noyau (events, policy, engine, safety), modules, plateformes, stockage, GUI
scripts/      run_dev.sh, download_models.py
tests/        tests unitaires, scénarios, smoke GUI
docs/         documentation technique (français)
models/       *.onnx locaux (jamais versionnés)
```

## Sécurité en bref

1. Le mode **SIMULATION est toujours actif au démarrage** ; activer la
   PROTECTION demande de saisir `PROTECTION` dans les Réglages.
2. Les empreintes sont chiffrées **AES-256-GCM**, clé dans le coffre clés
   système (Keychain / DPAPI / Secret Service selon la plateforme).
3. Aucune image brute, aucune touche tapée, aucune trajectoire de souris,
   aucun contenu d'app n'est conservé.
4. **L'anti-usurpation V0.2 (blink + texture) n'est pas une preuve de vivant
   robuste** — les limites sont documentées et à lire avant toute mise en
   mode PROTECTION : [docs/SECURITY.md](docs/SECURITY.md).

## Licence

Proprietary — voir le dépôt.
