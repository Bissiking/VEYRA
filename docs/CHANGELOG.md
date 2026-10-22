# CHANGELOG — VEYRA

Toutes les modifications significatives. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/) ; versions en
[CalVer simplifié](https://calver.org/) non applicable ici : sémantique
`MAJEUR.MINEUR.PATCH`.

## [0.1.0] — 2026-10-22

Première version fonctionnelle (V0.1) — plateforme de sécurité locale.

### Ajouté

#### Noyau
- `EventBus` thread-safe (pub/sub par type, isolation des exceptions).
- `SurveillanceEngine` : moteur de décision adaptatif
  (modes ACTIVE / LIGHT / PRIORITY, fenêtre de confirmation 2 s,
  règles verrouillage caméra, maintien d'absence, horloge injectable).
- `SecurityPolicy` centralisée et persistée (12 paramètres documentés).
- `SafetyCircuit` + `ActionExecutor` : coupe-circuit SIMULATION / PROTECTION,
  défaut **SIMULATION forcé à chaque démarrage**, activation PROTECTION avec
  confirmation explicite obligatoire, tous les verrouillages passent par
  l'exécuteur.
- `ModuleManager` : registre, démarrage global/individuel, publication de
  statuts ; interface `IVeyraModule` (`ModuleState`).

#### Modules
- `face_guard` : thread caméra (backoff, `CAMERA_STATUS`), pipeline YuNet +
  SFace (ONNX Runtime), classification TRUSTED / UNKNOWN / UNDETERMINED /
  NO_FACE avec contrôles de qualité (taille, luminosité), agrégation
  multi-visages, enrôlement multi-angles avec contrôle de diversité,
  dépôt de profils, suppression complète.
- `activity_guard` : flux pynput sans contenu (horodatages uniquement),
  vérification des autorisations macOS (`AXIsProcessTrusted`,
  `CGPreflightListenEventAccess`), états DEGRADED / UNAVAILABLE honnêtes.
- `session_guard` : relais unique décisions → exécuteur, sans accès plateforme.

#### Stockage
- SQLite (WAL) : `settings`, `events`, `profiles`, `schema_version`.
- `EventStore` sanitisé (aucune empreinte/image/touche persistée).
- `BiometricVault` : chiffrement AES-256-GCM, KEK en Keychain macOS,
  refus explicite sans coffre clés (jamais de stockage en clair).
- `ConfigStore` : politique + paramètres GUI persistants.

#### Plateformes
- `MacosAdapter` : verrouillage `osascript` (Ctrl+Cmd+Q), Keychain, capacités
  réelles ; échecs journalisés si permissions refusées.
- `WindowsAdapter` / `LinuxAdapter` : interfaces communes, capacités `False`,
  `NotImplementedError` explicite (aucune simulation).

#### Interface
- PySide6, thème sombre, navigation 5 pages :
  Dashboard (cartes d'état + derniers événements), Présence (aperçu caméra,
  enrôlement, statut de reconnaissance, suppression de profil), Modules
  (liste, états, activation, capacités plateforme), Events (filtre, historique,
  effacement), Settings (caméra, performances, délais, politiques, mode de
  protection avec confirmation, confidentialité).
- Icône de tray, fermeture masquante (surveillance persistante), sortie
  explicite (Ctrl+Shift+Q, menu tray).
- Pont `EventBus` → signaux Qt (`QueuedConnection`) : aucun blocage du
  thread GUI.

#### Outils et tests
- `scripts/run_dev.sh` : environnement + modèles + lancement.
- `scripts/download_models.py` : YuNet + SFace épinglés à un commit
  `opencv_zoo`, SHA-256 vérifié.
- 79 tests : moteur, coupe-circuit, scénarios d'intrusion sans webcam,
  stockage/chiffrement, bus, modules, pipeline, enrôlement, intégration
  bootstrap, smoke GUI offscreen.
- `.gitignore` (venv, modèles ONNX, SQLite, logs), `requirements*.txt`,
  `pyproject.toml`.

#### Documentation
- `docs/ARCHITECTURE.md`, `MODULES.md`, `SECURITY.md`, `DETECTION.md`,
  `SIMULATION.md`, `CONFIGURATION.md`, `INSTALLATION.md`, `ROADMAP.md`,
  ce `CHANGELOG.md` — tout en français, avec distinction
  implémenté / expérimental / planifié.

### Limites connues (V0.1)

- Aucune détection anti-usurpation (photo/vidéo) — documentée `SECURITY.md`.
- Windows/Linux non opérationnels (capacités affichées `False` en GUI).
- Enrôlement indisponible sans coffre clés (refus explicite).
- Permissions macOS requises pour l'activité et le verrouillage réel
  (états DEGRADED / lock échoué affichés, jamais masqués).
