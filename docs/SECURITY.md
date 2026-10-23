# SÉCURITÉ — VEYRA V0.2

Modèle de sécurité, traitement des données biométriques, limites connues et
protections en place.

## Modèle de menace (V0.2)

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
| Clé de chiffrement (KEK) | **Keychain macOS** / **DPAPI Windows** / **Secret Service Linux** | coffre système local |
| Événements / décisions | SQLite `events` | aucune donnée biométrique dedans |
| Paramètres | SQLite `settings` | — |

- **Aucune image brute n'est conservée** : les frames vivent en mémoire
  (`CameraWorker`) et sont abandonnées après inférence. L'enregistrement
  d'images n'est **pas implémenté** (paramètre présent mais inactif,
  la GUI l'indique explicitement).
- **Suppression complète** : `AppContext.delete_biometric_profile()` efface la
  ligne SQLite **et** l'entrée Keychain (`BiometricVault.destroy()`).
  Boutons dédiés : page Présence et page Réglages.
- **Journalisation** : `storage/event_store.py::_sanitize` rejette les clés
  `embedding`, `image`, `frame`, `keys`, `raw` avant persistance ; les journaux
  texte ne contiennent que des états, distances arrondies et motifs.

### Refus explicite plutôt que fallback

- Sur chaque plateforme, si le coffre clés système est indisponible
  (Keychain refusé, DPAPI échoue, `secret-tool` absent), l'enrôlement
  **échoue avec un message explicite** — aucune empreinte n'est écrite en clair.
- Si la KEK disparaît du coffre, le déchiffrement lève `KeyStorageError` et
  le profil est signalé « indéchiffrable » en GUI.

## Anti-usurpation (V0.2) — ce qui est fait et ce qui ne l'est pas

### Ce qui est implémenté (V0.2)

- **Détection de clignement** : le tracker observe l'ouverture des yeux
  (estimation à partir des 5 points YuNet) ; un cycle open→closed→open
  dans la fenêtre glissante compte comme un clignement.
- **Score de texture locale** : variance du Laplacien sur le ROI visage,
  indicateur grossier d'une surface plane (photo) vs peau vivante.
- **Dégradation, pas de verrouillage** : si les heuristiques déclenchent
  (`spoof_suspect`), un visage `TRUSTED` est dégradé en `UNKNOWN`. Aucune
  action agressive n'est prise sur un seul signal (faux positifs maîtrisés).

### Limites résiduelles (IMPORTANT)

> **Un deepfake ou une vidéo de haute qualité peut passer les heuristiques
> V0.2.** Le blink + la texture ne constituent pas une preuve de vivant
> robuste :
>
> - un attaquant qui fait cligneter quelqu'un (ou une vidéo avec clignements)
>   peut obtenir `TRUSTED` ;
> - un masque haut de gamme ou un écran haute définition peuvent tromper
>   le score de texture ;
> - il n'y a **pas** de détection de profondeur, d'Infrared, ni de modèle
>   d'anti-spoofing entraîné (SuFu, Silent-Face).
>
> La calibration locale (courbe FAR/FRR) permet d'ajuster les seuils à
> l'usage réel, mais ne change pas la nature des signaux utilisés.

Pistes documentées pour une V0.3+ : détection de parallaxe/mouvement,
challenge-réponse visuel, capteur de profondeur, modèle d'anti-spoofing
(SuFu, Silent-Face), intégration caméra IR.

Autres limites assumées :
- **Threshold** : la distance L2 SFace (0,636 par défaut) est une heuristique ;
  la zone grise (`recognition_margin`) renvoie `UNDETERMINED` pour éviter les
  décisions sur des cas limites, mais un réglage trop permissif augmente les
  faux positifs. La calibration locale (V0.2) permet de l'ajuster.
- **Permissions macOS** : sans Accessibilité/Surveillance, `activity_guard` est
  `DEGRADED` et le moteur ne reçoit plus d'activité — il bascule en mode léger
  et les règles exigeant une activité ne se déclenchent pas (état visible en
  GUI, jamais masqué). Sans Accessibilité, le verrouillage réel (`osascript`)
  échoue et le `LOCK_OUTCOME` est journalisé comme « échoué ».
- **Permissions Linux** : `loginctl` requis pour le verrouillage ;
  `secret-tool` requis pour le coffre clés. Absents → capacités `False`
  affichées, enrôlement refusé explicitement.
- **Permissions Windows** : DPAPI requis pour le coffre clés. Absent →
  enrôlement refusé explicitement.
- **Une seule session utilisateur** : le compte verrouillé n'est pas
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
