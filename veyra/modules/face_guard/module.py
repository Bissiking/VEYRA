# veyra/modules/face_guard/module.py
"""Module Face Guard : orchestre caméra, pipeline et cadence d'analyse.

Cadence pilotée par les demandes du moteur (``ANALYSIS_REQUEST``) et par
l'état du moteur (``ENGINE_STATE``) pour limiter la CPU :
- mode ACTIVE  : analyse à ``active_analysis_interval_s`` ;
- mode LIGHT   : analyse à ``light_analysis_interval_s`` ;
- prioritaire  : analyse immédiate (reprise d'activité après absence).

Le module publie uniquement des ``FACE_OBSERVATION`` (état + métriques de
qualité). Aucune image ni empreinte ne transite par le bus ni par SQLite.
"""

from __future__ import annotations

import logging
import threading
import time

from veyra.core.events import Event, EventBus, EventType
from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState
from veyra.core.policy import IdentityState, SecurityPolicy, SurveillanceMode
from veyra.modules.face_guard.camera import CameraWorker
from veyra.modules.face_guard.enrollment import EnrollmentSession, ProfileRepository
from veyra.modules.face_guard.models import ModelPaths, default_models_dir
from veyra.modules.face_guard.pipeline import FacePipeline

logger = logging.getLogger(__name__)


class FaceGuardModule(IVeyraModule):
    module_id = "face_guard"
    name = "Présence faciale"

    def __init__(self, bus: EventBus, policy: SecurityPolicy,
                 paths: ModelPaths | None = None,
                 profile_repo: ProfileRepository | None = None,
                 enrollment: EnrollmentSession | None = None,
                 camera_index: int = 0) -> None:
        self._bus = bus
        self._policy = policy
        self._paths = paths or ModelPaths(default_models_dir())
        self._pipeline = FacePipeline(self._paths)
        self._camera = CameraWorker(bus, camera_index)
        self._profiles = profile_repo
        self._enrollment = enrollment

        self._state = ModuleState.STOPPED
        self._detail = ""
        self._running = False
        self._thread: threading.Thread | None = None
        self._force_immediate = threading.Event()
        self._mode = SurveillanceMode.ACTIVE
        self._last_result_state = IdentityState.NO_FACE
        self._last_analysis_ts = 0.0
        self._analysis_count = 0
        self._frames_with_faces = 0
        self._low_power = False
        self._unsubs: list = []

    # ------------------------------------------------------------ propriétés

    @property
    def camera(self) -> CameraWorker:
        return self._camera

    @property
    def pipeline(self) -> FacePipeline:
        return self._pipeline

    def set_policy(self, policy: SecurityPolicy) -> None:
        self._policy = policy

    def set_camera_index(self, index: int) -> None:
        self._camera.set_index(index)

    def set_low_power(self, value: bool) -> None:
        self._low_power = value

    def request_priority_analysis(self) -> None:
        """Demande d'analyse immédiate (appelée par l'interface en cas de reprise)."""
        self._force_immediate.set()

    # ---------------------------------------------------------- cycle de vie

    def start(self) -> None:
        if self._running:
            return
        self._state = ModuleState.STARTING
        if not self._pipeline.load():
            self._state = ModuleState.ERROR
            self._detail = self._pipeline.error
            self._publish_status()
            # La caméra reste utile pour l'aperçu Presence même sans modèles.
            self._camera.start()
            logger.error("face_guard en erreur : %s", self._detail)
            return
        if self._enrollment is not None and not self._enrollment.vault.available:
            self._detail = ("Coffre clés indisponible : reconnaissance activera mais "
                            "l'enrôlement est désactivé (voir docs/SECURITY.md).")
        self._camera.start()
        self._running = True
        self._unsubs = [
            self._bus.subscribe(EventType.ENGINE_STATE, self._on_engine_state),
            self._bus.subscribe(EventType.ANALYSIS_REQUEST, self._on_analysis_request),
        ]
        self._thread = threading.Thread(target=self._loop, name="veyra-face", daemon=True)
        self._thread.start()
        self._state = ModuleState.RUNNING
        if not self._detail:
            self._detail = "Détection et reconnaissance locales actives."
        self._publish_status()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self._camera.stop()
        self._state = ModuleState.STOPPED
        self._detail = ""
        self._publish_status()

    def info(self) -> ModuleInfo:
        metrics: dict[str, object] = {
            "analyses": self._analysis_count,
            "last_state": self._last_result_state.value,
            "camera_ok": self._camera.available,
            "profile_loaded": bool(self._profiles and self._profiles.has_profile()),
        }
        if self._camera.available:
            metrics["faces_seen"] = self._frames_with_faces
        return ModuleInfo(self.module_id, self.name, self._state, self._detail, metrics)

    # ------------------------------------------------------ événements noyau

    def _on_engine_state(self, event: Event) -> None:
        try:
            self._mode = SurveillanceMode(event.data.get("mode", SurveillanceMode.ACTIVE.value))
        except ValueError:
            self._mode = SurveillanceMode.ACTIVE

    def _on_analysis_request(self, event: Event) -> None:
        if event.data.get("priority"):
            self._force_immediate.set()

    # --------------------------------------------------------------- boucle

    def _loop(self) -> None:
        while self._running:
            interval = self._current_interval()
            now = time.monotonic()
            forced = self._force_immediate.is_set()
            if forced:
                self._force_immediate.clear()
            elif now - self._last_analysis_ts < interval:
                time.sleep(0.1)
                continue
            try:
                self._analyze_once()
            except Exception:
                logger.exception("Erreur pendant l'analyse faciale.")
            self._last_analysis_ts = time.monotonic()
            time.sleep(0.05)

    def _current_interval(self) -> float:
        if self._mode is SurveillanceMode.LIGHT:
            base = self._policy.light_analysis_interval_s
        else:
            base = self._policy.active_analysis_interval_s
        if self._low_power:
            base *= 2.0
        return max(base, 0.5)

    def _analyze_once(self) -> None:
        ts, frame = self._camera.latest()
        if frame is None:
            # Caméra indisponible : le statut est déjà publié par CameraWorker.
            return
        reference = self._profiles.reference() if self._profiles else None
        result = self._pipeline.process(frame, self._policy, reference)
        self._analysis_count += 1
        if result.state is not IdentityState.NO_FACE:
            self._frames_with_faces += 1
        self._last_result_state = result.state

        data: dict[str, object] = {
            "state": result.state.value,
            "face_count": len(result.faces),
            "detail": result.detail,
        }
        if result.faces:
            # Métriques agrégées uniquement (aucune coordonnée individuelle stockée).
            data["best_score"] = round(max(f.score for f in result.faces), 3)
            distances = [round(f.distance, 3) for f in result.faces if f.distance is not None]
            if distances:
                data["best_distance"] = min(distances)
            data["min_brightness"] = round(min(f.brightness for f in result.faces), 1)
        self._bus.publish(Event(EventType.FACE_OBSERVATION, source=self.module_id,
                                data=data))

    # ---------------------------------------------------------------- GUI

    def enrollment_session(self) -> EnrollmentSession | None:
        return self._enrollment

    def _publish_status(self) -> None:
        info = self.info()
        self._bus.publish(Event(EventType.MODULE_STATUS, source=self.module_id, data={
            "state": info.state.value,
            "detail": info.detail,
            "metrics": info.metrics,
        }))
