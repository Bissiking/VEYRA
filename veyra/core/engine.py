# veyra/core/engine.py
"""Moteur de surveillance adaptatif VEYRA.

Responsabilités :
- suivre l'activité utilisateur (sans jamais connaître le détail des frappes) ;
- appliquer le rythme d'analyse adaptatif (actif / léger / prioritaire) ;
- combiner l'état d'identité facial et l'activité pour produire des décisions ;
- émettre les demandes de verrouillage vers le coupe-circuit (jamais directement
  vers la plateforme).

Le moteur est déterministe et pilotable par horloge injectée, ce qui permet
de le tester sans caméra ni attente réelle.

Règles V0.1 (références : docs/DETECTION.md) :
1. Pas d'activité pendant ``idle_threshold_s``  -> mode LIGHT (analyse espacée).
2. Reprise d'activité après absence             -> mode PRIORITY (analyse immédiate).
3. Visage inconnu confirmé pendant ``confirm_window_s`` + activité -> LOCK_SESSION.
4. Webcam indisponible après une absence + nouvelle activité       -> LOCK_SESSION
   (selon ``lock_on_camera_loss_after_absence``).
5. Absence du propriétaire sans activité        -> MAINTAIN_SESSION (une fois).
6. Tout LOCK_SESSION ne sort que par l'exécuteur (coupe-circuit).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from veyra.core.events import Event, EventBus, EventType
from veyra.core.policy import Decision, DecisionRecord, IdentityState, SecurityPolicy, SurveillanceMode

logger = logging.getLogger(__name__)

Clock = Callable[[], float]


class SurveillanceEngine:
    """Moteur de décision adaptatif basé sur les événements du bus."""

    def __init__(self, bus: EventBus, policy: SecurityPolicy, clock: Clock = time.monotonic) -> None:
        self._bus = bus
        self._policy = policy
        self._clock = clock
        self._lock = threading.RLock()

        # État observable
        self._last_activity: float | None = None
        self._identity: IdentityState = IdentityState.NO_FACE
        self._camera_ok: bool | None = None
        self._owner_absent_since: float | None = None
        self._suspicion_since: float | None = None
        self._lock_fired_for_unknown = False
        self._camera_lock_pending = False
        self._maintain_emitted_episode: float | None = None
        self._priority_since: float | None = None
        self._mode: SurveillanceMode = SurveillanceMode.ACTIVE
        self._running = False
        self._thread: threading.Thread | None = None

        self._unsubs = [
            bus.subscribe(EventType.ACTIVITY_DETECTED, self._on_activity),
            bus.subscribe(EventType.FACE_OBSERVATION, self._on_face),
            bus.subscribe(EventType.CAMERA_STATUS, self._on_camera),
        ]

    # ------------------------------------------------------------------ état

    @property
    def mode(self) -> SurveillanceMode:
        with self._lock:
            return self._mode

    @property
    def identity(self) -> IdentityState:
        with self._lock:
            return self._identity

    @property
    def last_activity_age(self) -> float | None:
        with self._lock:
            if self._last_activity is None:
                return None
            return self._clock() - self._last_activity

    def update_policy(self, policy: SecurityPolicy) -> None:
        with self._lock:
            self._policy = policy

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": self._mode.value,
                "identity": self._identity.value,
                "last_activity_age_s": (None if self._last_activity is None
                                        else round(self._clock() - self._last_activity, 2)),
                "camera_ok": self._camera_ok,
                "owner_absent": self._owner_absent_since is not None,
            }

    # ------------------------------------------------------- cycle de vie

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._loop, name="veyra-engine", daemon=True)
        self._thread.start()
        logger.info("Moteur de surveillance démarré.")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        logger.info("Moteur de surveillance arrêté.")

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    return
            try:
                self.tick()
            except Exception:
                logger.exception("Erreur dans la boucle du moteur.")
            time.sleep(0.5)

    # ------------------------------------------------------- événements bus

    def _on_activity(self, event: Event) -> None:
        with self._lock:
            now = self._clock()
            idle_for = float("inf") if self._last_activity is None else now - self._last_activity
            resumed = idle_for >= self._policy.idle_threshold_s
            self._last_activity = now

            if resumed:
                # Reprise après absence : analyse prioritaire immédiate.
                self._priority_since = now
                self._mode = SurveillanceMode.PRIORITY
                # La fenêtre de confirmation ne compte que pendant l'activité :
                # elle repart à chaque reprise.
                self._suspicion_since = None
                if self._camera_ok is False and self._identity is not IdentityState.TRUSTED:
                    # Webcam indisponible au moment d'une reprise d'activité
                    # alors que le propriétaire n'est pas vérifié.
                    self._camera_lock_pending = True
                self._publish_engine_state_locked()
                self._bus.publish(Event(EventType.ANALYSIS_REQUEST, source="engine",
                                        data={"priority": True, "reason": "activity_resumed"}))
            elif self._mode is SurveillanceMode.LIGHT:
                self._mode = SurveillanceMode.ACTIVE
                self._publish_engine_state_locked()

    def _on_face(self, event: Event) -> None:
        try:
            state = IdentityState(event.data.get("state", IdentityState.UNDETERMINED.value))
        except ValueError:
            state = IdentityState.UNDETERMINED
        now = self._clock()
        with self._lock:
            previous = self._identity
            self._identity = state

            if state is IdentityState.TRUSTED:
                self._owner_absent_since = None
                self._suspicion_since = None
                self._lock_fired_for_unknown = False
                self._maintain_emitted_episode = None
                self._camera_lock_pending = False
            elif state in (IdentityState.NO_FACE, IdentityState.UNKNOWN):
                if self._owner_absent_since is None:
                    # Première absence de la session (y compris avant d'avoir
                    # jamais vu le propriétaire).
                    self._owner_absent_since = now
                if state is IdentityState.UNKNOWN:
                    # La fenêtre de confirmation court depuis l'observation.
                    if self._suspicion_since is None:
                        self._suspicion_since = now
                else:  # NO_FACE : pas de visage, pas de suspicion à confirmer
                    self._suspicion_since = None
                    self._lock_fired_for_unknown = False
                if previous is not IdentityState.UNKNOWN:
                    # Nouvel épisode inconnu : réarme la décision de verrouillage.
                    self._lock_fired_for_unknown = False
            else:  # UNDETERMINED
                # Qualité insuffisante : ne confirme ni ne dément rien.
                pass

    def _on_camera(self, event: Event) -> None:
        ok = bool(event.data.get("ok", False))
        with self._lock:
            self._camera_ok = ok
            if not ok:
                # Sans caméra, la présence ne peut plus être vérifiée :
                # l'éventuel statut TRUSTED devient obsolète.
                if self._identity is IdentityState.TRUSTED:
                    self._identity = IdentityState.UNDETERMINED
                # Candidate au verrouillage seulement si une absence est déjà
                # constatée (règle « webcam indisponible après absence »).
                if self._owner_absent_since is not None:
                    self._camera_lock_pending = True
            else:
                self._camera_lock_pending = False

    # ----------------------------------------------------------- décision

    def tick(self, now: float | None = None) -> DecisionRecord | None:
        """Un pas de décision. Retourne une décision si une action est requise."""
        now = self._clock() if now is None else now
        with self._lock:
            policy = self._policy

            # --- 1. Adaptation du rythme
            idle_for = (float("inf") if self._last_activity is None
                        else now - self._last_activity)
            active = idle_for < policy.idle_threshold_s

            if not active:
                if self._mode is not SurveillanceMode.LIGHT:
                    self._mode = SurveillanceMode.LIGHT
                    self._priority_since = None
                    self._publish_engine_state_locked()
            elif self._mode is SurveillanceMode.LIGHT:
                self._mode = SurveillanceMode.ACTIVE
                self._publish_engine_state_locked()
            elif self._mode is SurveillanceMode.PRIORITY:
                # Priorité consommée après une durée d'analyse active.
                if (self._priority_since is not None
                        and now - self._priority_since >= policy.active_analysis_interval_s):
                    self._mode = SurveillanceMode.ACTIVE
                    self._priority_since = None
                    self._publish_engine_state_locked()

            # --- 2. Webcam indisponible après absence + nouvelle activité
            if (policy.lock_on_camera_loss_after_absence
                    and self._camera_lock_pending
                    and active
                    and self._camera_ok is False):
                self._camera_lock_pending = False  # une seule décision par épisode
                return self._decide(Decision.LOCK_SESSION,
                                    "camera_unavailable_after_absence_with_activity", now)

            # --- 3. Visage inconnu confirmé + activité
            if (policy.lock_on_unknown_face_with_activity
                    and self._identity is IdentityState.UNKNOWN
                    and active
                    and not self._lock_fired_for_unknown):
                if self._suspicion_since is None:
                    self._suspicion_since = now
                elif (now - self._suspicion_since) >= policy.confirm_window_s:
                    self._lock_fired_for_unknown = True
                    self._suspicion_since = None
                    return self._decide(Decision.LOCK_SESSION,
                                        "unknown_face_confirmed_with_activity", now)
            elif self._identity is not IdentityState.UNKNOWN:
                self._suspicion_since = None

            # --- 4. Absence du propriétaire sans activité -> maintien
            if (policy.absent_idle_keep_session
                    and self._identity in (IdentityState.NO_FACE, IdentityState.UNKNOWN)
                    and not active
                    and self._owner_absent_since is not None
                    and self._maintain_emitted_episode != self._owner_absent_since):
                self._maintain_emitted_episode = self._owner_absent_since
                return self._decide(Decision.MAINTAIN_SESSION,
                                    "owner_absent_without_activity", now)

            return None

    # -------------------------------------------------------------- privés

    def _decide(self, decision: Decision, reason: str, now: float) -> DecisionRecord:
        record = DecisionRecord(decision=decision, reason=reason,
                                identity_state=self._identity, mode=self._mode)
        self._bus.publish(Event(EventType.DECISION, source="engine", data={
            "decision": decision.value,
            "reason": reason,
            "identity": record.identity_state.value,
            "mode": record.mode.value,
        }))
        logger.info("Décision : %s (%s)", decision.value, reason)
        return record

    def _publish_engine_state_locked(self) -> None:
        self._bus.publish(Event(EventType.ENGINE_STATE, source="engine", data={
            "mode": self._mode.value,
            "identity": self._identity.value,
        }))
