# CONFIGURATION — VEYRA V0.1

Paramètres, valeurs par défaut et lieux de stockage.

## Stockage

- **Fichier** : `~/Library/Application Support/VEYRA/veyra.db` (SQLite, WAL).
  Sur Linux : `~/.local/share/veyra/veyra.db` ; Windows : `%LOCALAPPDATA%\VEYRA`.
- **Tables** : `settings` (clé/valeur JSON préfixées `config.`),
  `events` (historique), `profiles` (empreintes chiffrées), `schema_version`.
- **Journaux** : `~/Library/Application Support/VEYRA/logs/veyra.log`
  (rotation 2 Mo × 3).
- **Modèles ONNX** : `<racine du dépôt>/models/` ou `$VEYRA_MODELS_DIR`.
- **Clés** : Keychain macOS (service `veyra.biometric`, compte `profile_kek`).

Toute la configuration est modifiable depuis la page **Réglages** de la GUI ;
les valeurs sont appliquées en cours d'exécution (`AppContext.apply_policy`)
et persistées immédiatement.

## Politique de sécurité (`SecurityPolicy`)

| Clé | Défaut | Unité | Description |
|---|---|---|---|
| `idle_threshold_s` | 10 | s | Inactivité avant passage en surveillance légère |
| `light_analysis_interval_s` | 5 | s | Cadence d'analyse en mode léger |
| `active_analysis_interval_s` | 1 | s | Cadence d'analyse en mode actif |
| `confirm_window_s` | 2 | s | Fenêtre de confirmation d'un visage inconnu |
| `absent_idle_keep_session` | `true` | bool | Absence sans activité → maintien de session |
| `lock_on_unknown_face_with_activity` | `true` | bool | Inconnu confirmé + activité → verrouillage |
| `lock_on_camera_loss_after_absence` | `true` | bool | Webcam KO après absence + nouvelle activité → verrouillage |
| `recognition_threshold` | 0,636 | distance L2 | Seuil `TRUSTED` (recommandation SFace/OpenCV) |
| `recognition_margin` | 0,08 | distance L2 | Zone grise → `UNDETERMINED` entre seuil et seuil+marge |
| `min_face_size_px` | 80 | px | Visage plus petit → `UNDETERMINED` |
| `min_face_brightness` | 40 | 0-255 | Luminosité ROI plus faible → `UNDETERMINED` |
| `enrollment_samples` | 8 | count | Échantillons requis à l'enrôlement |

Plages acceptées par la GUI : seuils ×0,5–300 s ; `recognition_threshold`
0,1–1,5 ; index caméra 0–9.

## Autres paramètres (`ConfigStore`)

| Clé | Défaut | Description |
|---|---|---|
| `camera_index` | 0 | Indice de caméra OpenCV |
| `low_power` | `false` | Cadence d'analyse ÷ 2 (économie CPU) |
| `keep_raw_images` | `false` | **Inactif en V0.1** : l'enregistrement d'images n'est pas implémenté (la GUI l'indique) |
| `protection_mode` | `SIMULATION` | Dernier mode enregistré — **à titre indicatif seulement** : le démarrage force toujours SIMULATION |

## Dépassement par fichier (avancé)

Les valeurs sont lues au démarrage depuis SQLite ; pour les modifier hors GUI :

```bash
sqlite3 ~/Library/Application\ Support/VEYRA/veyra.db \
  "UPDATE settings SET value='{\"idle_threshold_s\": 30}' WHERE key='config.policy';"
```

Le JSON invalide est ignoré proprement (retour aux défauts, testé dans
`tests/test_storage.py::test_policy_invalide_ne_crash_pas`).

## Variables d'environnement

| Variable | Effet |
|---|---|
| `VEYRA_MODELS_DIR` | Dossier contenant les `.onnx` (défaut : `<dépôt>/models`) |
| `QT_QPA_PLATFORM=offscreen` | Lancement GUI sans fenêtre (tests/CI) |
