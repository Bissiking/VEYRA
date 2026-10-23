# MODULES — VEYRA V0.2

Fonctionnement des modules, interfaces communes et guide de création d'un
nouveau module.

## Interface commune

Chaque module implémente `veyra/core/module_api.py::IVeyraModule` :

```python
class IVeyraModule(ABC):
    module_id: str          # identifiant unique (snake_case)
    name: str               # libellé affiché dans la GUI

    def start(self) -> None: ...   # non bloquant, thread-safe
    def stop(self) -> None: ...    # libère toutes les ressources
    def info(self) -> ModuleInfo:  # état + détails + métriques
        ...
```

États possibles (`ModuleState`) :

| État          | Signification                                          |
|---------------|--------------------------------------------------------|
| `STOPPED`     | arrêté volontairement                                  |
| `STARTING`    | en cours de démarrage                                  |
| `RUNNING`     | opérationnel                                           |
| `DEGRADED`    | fonctionne partiellement (permission, ressource)       |
| `ERROR`       | en échec (message explicite)                           |
| `UNAVAILABLE` | non supporté sur la plateforme (jamais simulé)         |

## Règles pour tous les modules

1. **Un module ne verrouille jamais la session.** Il publie des observations ;
   seul `session_guard` relaie vers l'`ActionExecutor`.
2. **Communication uniquement via l'`EventBus`** (aucun import croisé entre modules).
3. **Aucune donnée sensible sur le bus** : pas d'image, pas d'empreinte, pas de touche.
4. **`start()`/`stop()` non bloquants** : les longues opérations vont dans un thread dédié.
5. **Les échecs sont signalés**, pas masqués : `state=ERROR` + `detail` explicite.

---

## Modules implémentés

### `face_guard` — Présence faciale (`veyra/modules/face_guard/`)

- **Rôle** : détection (YuNet), empreinte (SFace via ONNX Runtime), enrôlement
  multi-angles, comparaison au profil autorisé, anti-spoofing basique.
- **Sous-composants** :
  - `camera.py` (`CameraWorker`) : thread de capture, dernière frame en mémoire,
    publication `CAMERA_STATUS`, réessai avec backoff (2 s → 15 s).
  - `pipeline.py` (`FacePipeline`) : détection → alignement SFace → embedding
    128-D normalisé → classification (`TRUSTED` / `UNKNOWN` / `UNDETERMINED` /
    `NO_FACE`), extraction landmarks + texture.
  - `liveness.py` (`LivenessTracker`) : détection clignement + score texture,
    dégradation `TRUSTED`→`UNKNOWN` si suspect.
  - `calibration.py` : courbe FAR/FRR, seuil EER à partir des échantillons
    d'enrôlement.
  - `enrollment.py` (`EnrollmentSession`, `ProfileRepository`) : récolte d'échantillons
    avec contrôle de diversité d'angles, moyenne normalisée, chiffrement, SQLite.
  - `module.py` (`FaceGuardModule`) : boucle d'analyse à cadence variable selon
    le mode du moteur (`ANALYSIS_REQUEST` / `ENGINE_STATE`), échantillonnage
    liveness, collecte calibration.
- **Entrées bus** : `ENGINE_STATE`, `ANALYSIS_REQUEST`.
- **Sorties bus** : `CAMERA_STATUS`, `FACE_OBSERVATION`, `ENROLLMENT_PROGRESS`, `MODULE_STATUS`.
- **Métriques** : `analyses`, `last_state`, `camera_ok`, `profile_loaded`, `faces_seen`,
  `spoof_suspect`, `blinks`.
- **État particulier** : si les modèles ONNX sont absents, le module passe en
  `ERROR` avec le message « exécuter `scripts/download_models.py` ». L'aperçu
  caméra reste disponible. **Aucune reconnaissance simulée.**

### `activity_guard` — Activité (`veyra/modules/activity_guard/`)

- **Rôle** : publier un événement « il y a eu activité » (horodatage uniquement).
- **Garantie** : aucun code de touche, aucune position de souris, aucun contenu
  n'est stocké, journalisé ou transmis.
- **Implémentation** : `PynputActivityStream` (listeners clavier + souris).
- **macOS** : vérifie les autorisations via `AXIsProcessTrusted` et
  `CGPreflightListenEventAccess` ; sans elles, état `DEGRADED` avec le chemin
  d'accord dans les Réglages (aucun contournement).
- **Plateformes sans support** : `UNAVAILABLE`, visible en GUI (capacités
  honnêtes, jamais simulées).
- **Entrées bus** : —
- **Sorties bus** : `ACTIVITY_DETECTED`, `MODULE_STATUS`.

### `session_guard` — Verrouillage (`veyra/modules/session_guard/`)

- **Rôle** : relayer les décisions `LOCK_SESSION` du moteur vers l'exécuteur.
- **Ne détient aucun accès plateforme** : même en mode PROTECTION, tout passe
  par `core/safety.py::ActionExecutor`.
- **Entrées bus** : `DECISION`.
- **Sorties bus** : (via exécuteur) `LOCK_OUTCOME`, `MODULE_STATUS`.
- **Métriques** : `lock_requests`, `last_outcome` (`simulé` / `exécuté` / `échoué`).

---

## Développer un nouveau module (prévisionnel)

1. Créer `veyra/modules/<nom>/module.py` avec une classe `IVeyraModule`.
2. Publier ses observations sur le bus (`EventType` à ajouter dans `core/events.py`).
3. Se **limiter à des observations** : toute décision appartient au moteur,
   toute action sensible à l'exécuteur.
4. Enregistrer dans `bootstrap.py` : `self.modules.register(MonModule(...))`.
5. Documenter le module dans ce fichier et son état dans `docs/ROADMAP.md`
   (implémenté / expérimental / planifié).
6. Ajouter ses tests dans `tests/`.

> Aucun module supplémentaire n'est prévu en V0.2 (pas d'antivirus, pas de
> surveillance réseau — voir `docs/ROADMAP.md`).
