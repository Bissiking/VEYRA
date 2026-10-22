# SÉCURITÉ — VEYRA V0.1

Modèle de sécurité, traitement des données biométriques, limites connues et
protections en place.

## Modèle de menace (V0.1)

VEYRA protège contre : **un tiers utilisant la session pendant l'absence de
l'utilisateur** (présence non autorisée détectée par visage + activité).

VEYRA **ne protège PAS** contre (limites assumées) :
- un attaquant ayant accès physique prolongé à la machine **et** aux droits de
  l'utilisateur (il peut désactiver VEYRA) ;
- la collecte forensique locale par un utilisateur admin de la machine ;
- les attaques réseau (aucune fonction réseau dans cette version) ;
- l'usurpation biométrique sophistiquée (voir ci-dessous).

## Coupe-circuit de sécurité

Deux modes, définis dans `veyra/core/safety.py` :

| | SIMULATION (défaut à **chaque** démarrage) | PROTECTION |
|---|---|---|
| Détection | complète | complète |
| Décisions | calculées | calculées |
| Journalisation | complète | complète |
| Verrouillage réel | **jamais** (aucun appel plateforme) | possible, journalisé |

- L'activation PROTECTION exige une **confirmation explicite** (saisie de la
  chaîne `PROTECTION` dans la GUI) ; un booléen `confirmation=True` est exigé
  par l'API `SafetyCircuit.enable_protection()` (refus sans confirmation).
- Toutes les actions sensibles passent par `ActionExecutor.request_lock()` :
  c'est le **seul** point du système qui appelle `platform.lock_session()`.
- Le retour en SIMULATION est libre et immédiat.
- Tests : `tests/test_safety.py` (10 cas, dont « la simulation n'appelle
  JAMAIS la plateforme » et « une exception plateforme ne crashe pas »).

## Données biométriques

### Ce qui est stocké

| Donnée | Où | Protection |
|---|---|---|
| Empreinte faciale 128-D (moyenne d'échantillons) | SQLite `profiles.embedding_blob` | chiffrée **AES-256-GCM** (`cryptography`) |
| Clé de chiffrement (KEK) | **Keychain macOS** (`security`, service `veyra.biometric`) | coffre système |
| Événements / décisions | SQLite `events` | aucune donnée biométrique dedans |
| Paramètres | SQLite `settings` | — |

- **Aucune image brute n'est conservée** : les frames vivent en mémoire
  (`CameraWorker`) et sont abandonnées après inférence. L'enregistrement
  d'images n'est **pas implémenté** en V0.1 (paramètre présent mais inactif,
  la GUI l'indique explicitement).
- **Suppression complète** : `AppContext.delete_biometric_profile()` efface la
  ligne SQLite **et** l'entrée Keychain (`BiometricVault.destroy()`).
  Boutons dédiés : page Présence et page Réglages.
- **Journalisation** : `storage/event_store.py::_sanitize` rejette les clés
  `embedding`, `image`, `frame`, `keys`, `raw` avant persistance ; les journaux
  texte ne contiennent que des états, distances arrondies et motifs.

### Refus explicite plutôt que fallback

- Sans coffre clés fonctionnel (Windows/Linux en V0.1, Keychain refusé),
  l'enrôlement **échoue avec un message explicite** — aucune empreinte n'est
  écrite en clair.
- Si la KEK du Keychain disparaît, le déchiffrement lève `KeyStorageError` et
  le profil est signalé « indéchiffrable » en GUI.

## Limites de l'anti-usurpation (IMPORTANT)

> **Une photo ou une vidéo présentée à la webcam n'est pas détectée comme telle
> en V0.1.** Le pipeline ne comporte aucune détection de vivant (blink, texture,
> profondeur, Infrared). Conséquences :
>
> - la présence « TRUSTED » atteste d'une **correspondance d'empreinte**, pas
>   d'une preuve de présence vivante ;
> - un attaquant en possession d'une photo haute résolution du propriétaire
>   peut potentiellement obtenir un état `TRUSTED` ;
> - les contrôles actuels (taille minimale du visage, luminosité) réduisent les
>   faux positifs de mauvaise qualité, **pas** les usurpations par photo.
>
> Pistes documentées mais **non implémentées** (voir `docs/ROADMAP.md`) :
> détection de photos (mouvement/parallaxe), challenge-réponse visuel,
> capteur profondeur, modèles d'anti-spoofing (SuFu, Silent-Face).

Autres limites assumées :
- **Threshold** : la distance L2 SFace (0,636 par défaut) est une heuristique ;
  la zone grise (`recognition_margin`) renvoie `UNDETERMINED` pour éviter les
  décisions sur des cas limites, mais un réglage trop permissif augmente les
  faux positifs.
- **Permissions macOS** : sans Accessibilité/Surveillance, `activity_guard` est
  `DEGRADED` et le moteur ne reçoit plus d'activité — il bascule en mode léger
  et les règles exigeant une activité ne se déclenchent pas (état visible en
  GUI, jamais masqué). Sans Accessibilité, le verrouillage réel (`osascript`)
  échoue et le `LOCK_OUTCOME` est journalisé comme « échoué ».
- **Une seule session utilisateur** : le compte macOS verrouillé n'est pas
  différencié (VEYRA agit sur la session courante).

## Permissions macOS utilisées

| Permission | Usage | Comportement si refusée |
|---|---|---|
| Caméra | capture visages | `CAMERA_STATUS ok=false`, aperçu « indisponible », état visible |
| Accessibilité | écoute clavier/souris (`activity_guard`) | module `DEGRADED` + instructions |
| Surveillance des événements | idem (macOS ≥ 10.15) | idem |
| Accessibilité (System Events) | verrouillage réel en mode PROTECTION | `LOCK_OUTCOME executed=false` journalisé |

Aucun contournement de sécurité système : pas de `sudo`, pas de désactivation
SIP/TCC, pas d'installation de profil.

## Bonnes pratiques applicatives

- Base SQLite en WAL dans le dossier utilisateur (`~/Library/Application Support/VEYRA`).
- Logs en rotation (2 Mo × 3) sans données sensibles.
- Aucune dépendance cloud ; le réseau n'est utilisé que par
  `scripts/download_models.py` (téléchargement ponctuel, URL épinglées + SHA-256).
- Dépendances déclarées avec bornes de version dans `requirements.txt`.
