# ARCHITECTURE — VEYRA V0.1

Vue d'ensemble des composants, des flux de données et des règles d'interaction.

## Principes

1. **Local intégral** : aucun service cloud, aucun réseau requis (hors téléchargement initial des modèles ONNX).
2. **Modularité** : chaque capacité vit dans un module communiquant uniquement via le bus d'événements.
3. **Séparation décision / action** : seul `core/safety.py` peut déclencher un verrouillage réel.
4. **Aucun droit administrateur** pour les fonctions de base (sous réserve des autorisations accordées par macOS).
5. **Threads isolés** : le thread principal Qt ne traite jamais d'image ni d'inférence.

## Structure du dépôt

```
veyra/                      # paquet Python
  app.py                    # point d'entrée (logging, contexte, boucle Qt)
  bootstrap.py              # composition : services + modules + moteur
  core/
    events.py               # EventBus thread-safe (pub/sub, Event, EventType)
    policy.py               # SecurityPolicy, IdentityState, Decision, modes
    engine.py               # SurveillanceEngine (moteur adaptatif de décision)
    safety.py               # SafetyCircuit + ActionExecutor (coupe-circuit)
    module_api.py           # IVeyraModule, ModuleInfo, ModuleState
    module_manager.py       # registre, démarrage/arrêt, publication de statuts
  modules/
    face_guard/             # caméra, pipeline YuNet+SFace, enrôlement, profils
    activity_guard/         # flux pynput (horodatages seulement)
    session_guard/          # relais décision -> exécuteur (aucun accès plateforme)
  platforms/
    base.py                 # PlatformAdapter, PlatformCapabilities
    macos.py                # implémentée (verrouillage osascript, keychain)
    windows.py              # interface prévisionnelle NON opérationnelle (V0.1)
    linux.py                # interface prévisionnelle NON opérationnelle (V0.1)
    factory.py              # sélection selon sys.platform
  storage/
    database.py             # SQLite (settings, events, profiles)
    config.py               # Configuration persistante
    event_store.py          # persistance des événements du bus (sanitisée)
    biometrics.py           # coffre clés plateforme + chiffrement AES-GCM
  gui/
    app (veyra/app.py)      # QApplication, thème, wiring du pont Qt
    bridge.py               # EventBus -> signaux Qt (queued, thread principal)
    main_window.py          # navigation 5 pages + tray + fermeture masquante
    theme.py                # thème sombre QSS + icône dessinée
    widgets.py              # Card, PageHeader, StateBadge
    pages/                  # dashboard, presence, modules_page, events_page, settings_page
scripts/
  run_dev.sh                # lancement développement local
  download_models.py        # YuNet + SFace (URLs épinglées, SHA-256 vérifié)
tests/                      # tests unitaires + scénarios + smoke GUI
docs/                       # documentation (français)
models/                     # *.onnx téléchargés, jamais versionnés (.gitignore)
```

## Flux de données principal

```
pynput (activity_guard)                    webcam (CameraWorker, thread dédié)
      │  ACTIVITY_DETECTED                       │ dernière frame (mémoire)
      ▼                                          ▼
 ┌───────────────────────────── EventBus ─────────────────────────────┐
 │                                                                    │
 │  FACE_OBSERVATION (state, métriques qualité)   CAMERA_STATUS       │
 │            │                                          │            │
 │            ▼                                          ▼            │
 │               SurveillanceEngine (core/engine.py)                  │
 │               - rythme ACTIVE / LIGHT / PRIORITY                   │
 │               - règles de décision (fenêtre de confirmation)       │
 │                        │ DECISION (LOCK_SESSION / MAINTAIN)        │
 │                        ▼                                           │
 │               SessionGuardModule (seul relais)                     │
 │                        │ LockRequest                               │
 │                        ▼                                           │
 │               ActionExecutor (core/safety.py)                      │
 │               - mode SIMULATION -> journal simulé, aucun appel      │
 │               - mode PROTECTION -> platform.lock_session()         │
 └────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                          GuiBridge (signaux Qt queued)
                                     │
                                     ▼
                     MainWindow / pages (thread principal Qt)
```

## Threads

| Thread              | Rôle                                    | Bloque la GUI ? |
|---------------------|-----------------------------------------|-----------------|
| Qt principal        | rendu, signaux, timers                  | —               |
| `veyra-camera`      | capture OpenCV, ~10 fps                 | non            |
| `veyra-face`        | détection + empreinte à cadence variable| non            |
| `veyra-engine`      | tick de décision (0,5 s)                | non            |
| `veyra-enrollment`  | récolte multi-angles (session unique)   | non            |
| listeners pynput    | écoute événements système               | non            |

La communication inter-threads passe exclusivement par l'`EventBus` (lock RLock)
et par le `GuiBridge` (signaux Qt en `QueuedConnection`).

## Cycle de vie

1. `veyra/app.py` : logging -> `AppContext(db)` -> **mode SIMULATION forcé**.
2. `QApplication` + thème + `GuiBridge` + `MainWindow` (les pages sont construites une fois).
3. `ctx.start()` : moteur puis modules (échecs isolés, états publiés).
4. Boucle Qt. Fermeture de fenêtre -> masquage ; « Quitter » -> `ctx.stop()`.
5. `ctx.stop()` : modules -> moteur -> event_store -> SQLite.

## Conventions

- Chaque fichier Python commence par une ligne de commentaire indiquant son chemin.
- Les événements publiés sur le bus sont sanitizés avant persistance
  (`storage/event_store.py::_sanitize`) : aucune empreinte, image ou touche.
- Les capacités non disponibles sont exposées `False` dans `PlatformCapabilities`
  et affichées en clair dans la GUI — jamais simulées silencieusement.
