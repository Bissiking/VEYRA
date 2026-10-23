# SIMULATION — VEYRA V0.2

Coupe-circuit de sécurité, modes de fonctionnement et scénarios de test.

## Pourquoi un mode SIMULATION ?

Une plateforme de verrouillage de session peut causer des déni de service
auto-infligés (verrouillage à tort, verrouillage pendant une démonstration).
La V0.2 démarre donc **toujours** en SIMULATION : toutes les détections,
décisions et journalisations fonctionnent, mais **aucune action réelle n'est
exécutée**. Le passage en mode réel est un choix conscient et confirmé.

## Les deux modes

```
                    ┌──────────────────────────────────────────────┐
                    │              ActionExecutor                  │
décision            │  request_lock(LockRequest)                   │
LOCK_SESSION ──────►│     │                                         │
(session_guard)     │     ├─ SIMULATION ─► journal + événement      │
                    │     │                 simulated=true          │
                    │     │                 executed=false          │
                    │     │                 locker JAMAIS appelé ◄──┼── garantie testée
                    │     │                                         │
                    │     └─ PROTECTION ─► platform.lock_session()  │
                    │                       executed=true/false     │
                    │                       journal complet         │
                    └──────────────────────────────────────────────┘
```

| Aspect | SIMULATION | PROTECTION |
|---|---|---|
| Détection visage / activité | oui | oui |
| Moteur de décision | oui | oui |
| Fenêtres de confirmation | oui | oui |
| Journalisation (SQLite + logs) | oui | oui |
| Verrouillage réel | **non** | **oui** (selon politiques) |
| Défaut au démarrage | **oui (toujours)** | activation explicite seulement |

## Activation / désactivation

- **Activer la PROTECTION** : page Réglages → « Activer la protection réelle… »
  → saisie de la chaîne `PROTECTION` (confirmation explicite) →
  `SafetyCircuit.enable_protection(True)`.
  API : un appel sans `confirmation=True` est refusé et journalisé.
- **Revenir en SIMULATION** : bouton dédié, immédiat, sans confirmation.
- **Au démarrage** : `veyra/app.py` force `revert_to_simulation()` après
  chargement du contexte — quel que soit l'état précédemment enregistré.

Affichages : badge `SIMULATION`/`PROTECTION` en bas de la barre latérale,
carte « Protection » du Dashboard, groupe « Mode de protection » des Réglages,
événement `PROTECTION_MODE_CHANGED` journalisé.

## Événements liés au mode

| Événement | Contenu |
|---|---|
| `protection_mode_changed` | `mode` |
| `lock_outcome` | `executed`, `simulated`, `mode`, `reason`, `request_source` |

Notification de tray à chaque `lock_outcome` : « Verrouillage simulé : … »,
« Session verrouillée (mode PROTECTION) » ou « Verrouillage échoué : … ».

## Scénarios de test

### Automatisés (135 tests : `python -m pytest tests/`)

| Fichier | Couverture |
|---|---|
| `test_safety.py` | défaut SIMULATION ; **simulation n'appelle jamais la plateforme** (5 demandes, 0 appel) ; confirmation obligatoire ; exécution réelle en PROTECTION ; retour libre ; échec et exception plateforme signalés ; événements `lock_outcome` ; idempotence |
| `test_engine.py` | rythme adaptatif ; confirmation 2 s ; maintien d'absence ; règle caméra ; politiques désactivables ; obsolétence TRUSTED sans caméra |
| `test_scenarios.py` | intrusion complète **sans webcam** (flux synthétiques) en simulation et en protection ; propriétaire reconnu ; caméra absente ; inactivité prolongée ; session_guard ignore les non-lock |
| `test_gui_smoke.py` | construction des 5 pages offscreen ; fermeture masque sans quitter |
| `test_bootstrap.py` | cycle démarrage/arrêt ; mode forcé ; politiques persistées |
| `test_face_pipeline.py` | états, agrégation multi-visages, refus sans modèle |
| `test_enrollment.py`, `test_storage.py`, `test_events.py`, `test_modules.py` | enrôlement, SQLite/chiffrement, bus, registre |

### Manuel (recommandé avant toute mise en mode PROTECTION)

1. `./scripts/run_dev.sh` → démarrage en SIMULATION (badge visible).
2. Enrôler un visage (page Présence) → observation `TRUSTED` au Dashboard.
3. Se couvrir la webcam / couper la caméra → `UNKNOWN`/`UNDETERMINED` affiché.
4. Sortir du champ pendant 10 s, revenir, rester immobile → mode LIGHT puis
   analyse prioritaire (journaux : `Moteur : mode …`).
5. Page Events : vérifier la présence des décisions et des verrouillages
   **simulés** ; notification tray « Verrouillage simulé ».
6. Activer la PROTECTION (saisie `PROTECTION`) → reproduire le scénario →
   notification « Session verrouillée » + `lock_outcome executed=true`.
   Puis revenir immédiatement en SIMULATION.
7. Redémarrer l'application → **retour forcé en SIMULATION**.

### Vérification du coupe-circuit par la console

```bash
python - <<'EOF'
from veyra.core.safety import SafetyCircuit, ActionExecutor, LockRequest
from veyra.core.events import EventBus

class FakeLocker:                      # « plante » si appelé en simulation
    def lock_session(self):
        raise AssertionError("appel plateforme en SIMULATION !")

bus = EventBus()
circuit = SafetyCircuit(bus)
executor = ActionExecutor(circuit, FakeLocker(), bus)
out = executor.request_lock(LockRequest("test", "demo", {}))
print("mode:", circuit.mode.value, "| simulé:", out.simulated, "| exécuté:", out.executed)
EOF
```

Sortie attendue : `mode: SIMULATION | simulé: True | exécuté: False`
(et aucune `AssertionError`).

## Garantie d'implémentation

- Le mode est détenu **uniquement** par `SafetyCircuit` ; les modules ne
  peuvent pas l'ignorer car ils n'ont aucun accès à la plateforme.
- `ActionExecutor` est le **seul** appelant de `platform.lock_session()`
  (vérifiable par recherche de `lock_session` dans le dépôt).
- En mode PROTECTION, la capacité de verrouillage dépend de la plateforme :
  si l'adaptateur ne supporte pas le verrouillage (capacité `False` ou
  outil système absent), l'échec est proprement journalisé — jamais de faux
  « exécuté ».
