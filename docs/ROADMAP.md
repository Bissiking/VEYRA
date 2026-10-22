# ROADMAP — VEYRA

État des fonctionnalités et évolutions prévues. Toute évolution est reportée
dans `CHANGELOG.md` et documentée dans les fichiers concernés.

Légende : **✅ implémenté (testé)** · **⚠️ expérimental** · **📋 planifié (non implémenté)**

---

## V0.1 — version actuelle

### ✅ Implémenté et testé (79 tests)

| Fonctionnalité | Détail |
|---|---|
| Noyau événementiel | `EventBus` thread-safe, isolation des exceptions |
| Moteur de décision adaptatif | modes ACTIVE/LIGHT/PRIORITY, 4 règles, horloge injectable |
| Coupe-circuit SIMULATION/PROTECTION | exécuteur unique, confirmation explicite, défaut SIMULATION forcé |
| Reconnaissance faciale locale | YuNet + SFace (ONNX Runtime), états TRUSTED/UNKNOWN/UNDETERMINED/NO_FACE, multi-visages |
| Enrôlement multi-angles | diversité d'angles, chiffrement AES-256-GCM, clé Keychain macOS |
| Suppression complète du profil | ligne SQLite + entrée Keychain |
| Surveillance d'activité | pynput, horodatages seuls, vérification des permissions macOS |
| Relais de verrouillage | `session_guard` → exécuteur (aucun accès plateforme) |
| Persistance SQLite | settings, events (sanitisés), profiles |
| GUI PySide6 sombre | 5 pages, tray, fermeture masquante, sortie explicite |
| Adaptateur macOS | verrouillage `osascript`, Keychain, capacités réelles |
| Adaptateurs Windows/Linux | interfaces communes, capacités `False` affichées |
| Scripts | `run_dev.sh`, `download_models.py` (URLs épinglées + SHA-256) |
| Tests | unitaires, scénarios d'intrusion sans webcam, smoke GUI offscreen |
| Documentation | `docs/` (9 fichiers FR) + README |

### ⚠️ Expérimental / limité (comportement réel connu)

| Élément | Limite |
|---|---|
| Verrouillage macOS | nécessite l'autorisation Accessibilité ; échec journalisé si refusé |
| Flux d'activité | nécessite Accessibilité + Surveillance ; `DEGRADED` sinon |
| Seuils biométriques | valeurs par défaut non calibrées sur corpus (à ajuster en usage réel) |
| Pipeline hors macOS | multiplateforme « théorique », validé uniquement sur macOS |

### 📋 Limites assumées de la V0.1

- **Anti-usurpation** : aucune détection photo/écran (voir `SECURITY.md`).
- **Un seul profil utilisateur** autorisé (schéma déjà multi-profils).
- **Aucune détection réseau / antivirus** (hors périmètre, volontairement).
- **Windows/Linux** : plateformes cibles mais non opérationnelles en V0.1.

---

## V0.2 — priorité haute (prévisionnel)

| Fonctionnalité | État | Notes |
|---|---|---|
| Anti-spoofing basique (blink/texture) | 📋 | premier jalon pour limiter les photos |
| Calibration des seuils depuis l'UI (courbe FAR/FRR locale) | 📋 | basée sur les échantillons d'enrôlement |
| Verrouillage Windows (`LockWorkStation`) | 📋 | adaptateur existant à compléter |
| Verrouillage Linux (`loginctl lock-session`) | 📋 | idem |
| Coffre clés Windows (DPAPI) / Linux (Secret Service) | 📋 | débloque l'enrôlement hors macOS |
| Démarrage au login (option utilisateur) | 📋 | agent utilisateur, pas de daemon root |

## V0.3 — priorité moyenne (prévisionnel)

| Fonctionnalité | État |
|---|---|
| Plusieurs profils utilisateurs (interface de gestion) | 📋 |
| Verrouillage automatique configurable (délai après décision) | 📋 |
| Export/import des paramètres | 📋 |
| Notifications système enrichies (erreur caméra, permission) | 📋 |
| Journalisé avec rotation/filtrage avancé dans la GUI | 📋 |

## Hors périmètre (délibéré)

- Cloud, serveur, synchronisation multi-appareils.
- Conteneurisation (Docker).
- Antivirus, pare-feu, surveillance réseau.
- Capture de contenu d'applications, keylogging, historique souris.
- Contournement de toute protection macOS (TCC, SIP).

---

## Politique documentaire

1. Une fonctionnalité n'apparaît comme **implémentée** qu'après merge avec tests.
2. Les éléments 📋 ne doivent jamais être présentés comme utilisables.
3. Toute évolution significative met à jour `CHANGELOG.md`.
4. `ARCHITECTURE.md` / `MODULES.md` / `DETECTION.md` sont mis à jour à chaque
   changement structurel.
