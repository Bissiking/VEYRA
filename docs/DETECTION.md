# DÉTECTION — VEYRA V0.2

Reconnaissance faciale, surveillance adaptative et moteur de décision.

## 1. Reconnaissance faciale

### Chaîne de traitement (`veyra/modules/face_guard/pipeline.py`)

```
frame BGR (CameraWorker, ~10 fps)
   → YuNet (cv2.FaceDetectorYN, score ≥ 0.6, NMS 0.3)      [détection + landmarks]
   → alignement SFace (cv2.FaceRecognizerSF.alignCrop)      [5 points]
   → prétraitement (x-127.5)/127.5, NCHW
   → SFace ONNX Runtime (1,3,112,112) → vecteur 128-D       [empreinte]
   → L2-normalisation
   → distance L2 vs empreinte de référence du profil
   → classification par visage → agrégation multi-visages
   → liveness (blink + texture) → dégradation si spoof suspect
```

Modèles locaux (`scripts/download_models.py`, URL épinglées + SHA-256) :
- `face_detection_yunet_2023mar.onnx` (232 Ko, OpenCV Zoo)
- `face_recognition_sface_2021dec.onnx` (38 Mo, OpenCV Zoo)

### États (`IdentityState`)

| État | Condition |
|---|---|
| `TRUSTED` | distance ≤ `recognition_threshold` (0,636) **et** qualité suffisante |
| `UNKNOWN` | distance > `recognition_threshold + recognition_margin` (0,716) |
| `UNDETERMINED` | zone grise, luminosité < 40, visage < 80 px, empreinte absente, **ou aucun profil enrôlé** |
| `NO_FACE` | aucun visage détecté |

Qualité (`SecurityPolicy`) : `min_face_brightness=40` (moyenne du ROI en gris),
`min_face_size_px=80`. Conditions non remplies → `UNDETERMINED` (jamais
`TRUSTED`, jamais interprété comme une intrusion).

### Anti-spoofing (`veyra/modules/face_guard/liveness.py`)

Le `LivenessTracker` reçoit, pour chaque analyse, l'ouverture des yeux et le
score de texture du meilleur visage. Fenêtre glissante (défaut 8 s) :

- **Blink** : ouverture yeux open → closed → open dans la fenêtre.
- **Texture** : variance du Laplacien sur le ROI visage (indicatif plan vs
  peau).
- **Suspicion** : assez de données **ET** blinks < `liveness_min_blinks` **ET**
  texture < `liveness_min_texture` — les deux signaux doivent être bas
  (un seul signal n'élève pas de suspicion).
- **Effet** : un visage `TRUSTED` mais suspect est publié en `UNKNOWN`.
  Jamais de verrouillage immédiat, jamais d'`ERROR`.

Les heuristiques sont documentées dans `SECURITY.md` (limites résiduelles).

### Calibration locale (`veyra/modules/face_guard/calibration.py`)

- Les distances L2 des échantillons d'enrôlement (genuine) et des visages
  `UNKNOWN` observés (impostor) sont collectés **localement**.
- `far_frr_curve` construit la courbe ; `equal_error_point` trouve le seuil
  EER. Appliqué via les Réglages → seuil de reconnaissance ajusté.
- Aucune image ni empreinte ne quitte l'appareil.

### Multi-visages

Agrégation (`_aggregate`) : si **au moins un** visage est `TRUSTED` → `TRUSTED`
(le propriétaire est présent) ; sinon si au moins un `UNKNOWN` → `UNKNOWN` ;
sinon `UNDETERMINED`.

### Enrôlement (page Présence)

1. Un seul profil autorisé (`user_key="owner"`), architecture
   multi-profils déjà en place (table `profiles`, `user_key` unique).
2. Récolte de `enrollment_samples` (8) échantillons, **un seul visage** exigé,
   cadence 0,25 s, timeout 3 min.
3. Diversité d'angles : un échantillon est rejeté si l'écart cumulé
   (position relative du visage) < 0,06 des échantillons retenus → invite à
   tourner la tête (`orientation_hint`).
4. Moyenne des empreintes → L2-normalisation → chiffrement AES-GCM → SQLite.
5. Les images sont abandonnées à chaque itération (`del frame`).

### Erreurs et conditions dégradées

| Situation | Comportement |
|---|---|
| Caméra absente / refusée | `CAMERA_STATUS ok=false`, détail visible, retry backoff 2→15 s |
| Modèles ONNX manquants | module `ERROR` + commande de téléchargement ; aperçu toujours dispo |
| Éclairage insuffisant | `UNDETERMINED` + `min_brightness` publié |
| Visage trop petit | `UNDETERMINED` |
| Aucun profil enrôlé | `UNDETERMINED` (jamais de « confiance » sans référence) |
| Échec embedding | `UNDETERMINED` (jamais de ranking silencieux) |

Limites anti-usurpation : voir `docs/SECURITY.md`.

## 2. Surveillance adaptative

### Modes (`SurveillanceMode`)

| Mode | Déclencheur | Cadence d'analyse |
|---|---|---|
| `ACTIVE` | activité récente (< `idle_threshold_s` = 10 s) | `active_analysis_interval_s` (1 s) |
| `LIGHT` | ≥ 10 s sans activité | `light_analysis_interval_s` (5 s) |
| `PRIORITY` | reprise d'activité après absence | **immédiate** (`ANALYSIS_REQUEST`) puis retour à `ACTIVE` après 1 s |

- Mode économe (GUI) : cadence ×2.
- Le moteur ne déclenche des analyses que quand c'est nécessaire :
  les ticks sans besoin ne publient rien (CPU limité).
- L'activité est suivie par horodatage **uniquement** (aucun détail de frappe).

### Règles du moteur (`core/engine.py::tick`)

Référence de code : `veyra/core/engine.py`, tests : `tests/test_engine.py`.

1. **Adaptation du rythme** : inactivité ≥ 10 s → `LIGHT` ; reprise → `PRIORITY`
   (analyse prioritaire demandée) puis `ACTIVE`.
2. **Webcam indisponible après absence + nouvelle activité** →
   `LOCK_SESSION` (règle `camera_unavailable_after_absence_with_activity`,
   configurable via `lock_on_camera_loss_after_absence`, défaut **activé**).
   Déclencheurs : caméra tombe pendant une absence constatée, **ou** reprise
   d'activité alors que caméra KO et propriétaire non vérifié.
   Une seule décision par épisode ; annulé si la caméra revient.
3. **Visage inconnu confirmé + activité** → `LOCK_SESSION` après
   `confirm_window_s` (2 s) de présence `UNKNOWN` continue pendant l'activité
   (`lock_on_unknown_face_with_activity`, défaut activé).
   - la fenêtre court **depuis l'observation** UNKNOWN, pas depuis le tick ;
   - elle repart à chaque reprise d'activité ;
   - un seul verrouillage par épisode UNKNOWN (réarmement au retour de
     `TRUSTED` ou `NO_FACE`).
4. **Absence du propriétaire sans activité** → `MAINTAIN_SESSION`
   (une fois par épisode d'absence, `absent_idle_keep_session`).
5. **Propriétaire reconnu** (`TRUSTED`) → réinitialise suspicion, absence et
   candidature caméra.

### Sensibilité caméra

Perte de caméra pendant un statut `TRUSTED` → l'identité devient
`UNDETERMINED` (le statut de confiance devient obsolète : sans capteur, la
présence n'est plus vérifiable).

### Journalisation

Chaque décision produit un événement `DECISION`
(`decision`, `reason`, `identity`, `mode`) persisté dans SQLite et visible dans
la page Events. Les verrouillages produisent `LOCK_OUTCOME`
(`executed`/`simulated`, `reason`, `mode`).

## 3. Moteur de décision — caractéristiques

- **Déterministe** : horloge injectée (`clock=`) → testable sans attente réelle.
- **Événementiel** : s'abonne à `ACTIVITY_DETECTED`, `FACE_OBSERVATION`,
  `CAMERA_STATUS` ; tick optionnel pour les fenêtres temporelles.
- **Aucun accès plateforme** : ne produit que des `DecisionRecord`.
- **Thread dédié** : tick 0,5 s, exceptions capturées (jamais d'arrêt brutal).

## 4. Scénarios de référence (tests)

| Scénario | Test | Attendu |
|---|---|---|
| Inconnu actif 2 s | `test_verrouillage_apres_confirmation_inconnu_active` | `LOCK_SESSION` une fois |
| Inconnu sans activité | `test_pas_de_verrouillage_si_activite_arrete_inconnu` | `MAINTAIN_SESSION` |
| Absent + inactivité | `test_absence_sans_activite_maintient_session` | `MAINTAIN_SESSION` une fois |
| Webcam perdue + reprise | `test_verrouillage_webcam_apres_absence_puis_activite` | `LOCK_SESSION` |
| Politique caméra désactivée | `test_politique_camera_desactivee_bloque_la_regle` | aucun lock |
| Propriétaire reconnu | `test_proprietaire_reconnu_ne_verrouille_rien` | aucun lock |
| Chaîne complète en simulation | `test_intrusion_confirmee_simulee_sans_verrouiller` | décision + verrou **simulé** |
| Chaîne complète en protection | `test_meme_scenario_en_protection_verrouille_reellement` | verrou **réel** appelé |
