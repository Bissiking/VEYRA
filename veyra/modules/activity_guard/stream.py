# veyra/modules/activity_guard/stream.py
"""Flux d'activité : détection de mouvement utilisateur SANS contenu.

Garanties V0.1 :
- aucun code de touche, aucun texte tapé n'est ni stocké, ni journalisé, ni transmis ;
- seul un horodatage « il y a eu une activité » est produit ;
- la souris n'émet que des événements de mouvement/clic grossiers (pas de trajectoire).

Implémentation : pynput (écoute passive). Si le système refuse l'autorisation
(macOS : Accessibilité / Surveillance clavier), le flux signale l'échec —
aucune simulation de données.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

ActivityCallback = Callable[[], None]


def macos_input_permissions() -> tuple[bool, str]:
    """Vérifie les autorisations macOS requises pour l'écoute d'événements.

    Retourne ``(autorisé, message)``. Utilise les API système officielles
    (AXIsProcessTrusted / CGPreflightListenEventAccess) — aucun contournement.
    N'est appelé que sur macOS.
    """
    import ctypes
    import sys

    if sys.platform != "darwin":
        return True, ""

    # Accessibilité (contrôle d'Applications par l'app)
    trusted = False
    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        app_services.AXIsProcessTrusted.restype = ctypes.c_bool
        trusted = bool(app_services.AXIsProcessTrusted())
    except OSError:
        trusted = False

    # Surveillance des événements (Input Monitoring)
    listen_ok = False
    try:
        core_graphics = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        core_graphics.CGPreflightListenEventAccess.restype = ctypes.c_bool
        listen_ok = bool(core_graphics.CGPreflightListenEventAccess())
    except (OSError, AttributeError):
        listen_ok = trusted  # API absente (macOS ancien) : Accessibilité suffit

    if trusted and listen_ok:
        return True, ""
    parts = []
    if not trusted:
        parts.append("Accessibilité")
    if not listen_ok:
        parts.append("Surveillance des événements")
    return False, (
        "Autorisation macOS manquante : " + " + ".join(parts) +
        " (Réglages > Confidentialité et sécurité). Sans elle, VEYRA ne reçoit "
        "aucun signal d'activité et reste en surveillance légère."
    )


class ActivityStream:
    """Interface d'un flux d'activité : start/stop + callback sans argument."""

    name = "activity_stream"

    def start(self, on_activity: ActivityCallback) -> bool:
        """Démarre le flux. Retourne False si indisponible/permission refusée."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    @property
    def active(self) -> bool:
        return False

    @property
    def last_error(self) -> str:
        return ""


class PynputActivityStream(ActivityStream):
    """Flux basé sur pynput : écoute clavier + souris, ne retient que des horodatages."""

    name = "pynput"

    def __init__(self) -> None:
        self._listener = None
        self._on_activity: ActivityCallback | None = None
        self._lock = threading.Lock()
        self._active = False
        self._error = ""

    def start(self, on_activity: ActivityCallback) -> bool:
        with self._lock:
            if self._active:
                return True
            self._on_activity = on_activity
        try:
            from pynput import keyboard, mouse
        except Exception as exc:  # import impossible sur cette plateforme
            self._error = f"pynput indisponible : {exc}"
            logger.error(self._error)
            return False

        def _fire() -> None:
            cb = self._on_activity
            if cb is not None:
                try:
                    cb()
                except Exception:
                    logger.exception("Erreur dans le callback d'activité.")

        # Les handlers ignorent volontairement la valeur de la touche / position.
        def on_press(key: object) -> None:
            _fire()

        def on_move(x: int, y: int) -> None:
            _fire()

        def on_click(x: int, y: int, button: object, pressed: bool) -> None:
            _fire()

        def on_scroll(dx: int, dy: int) -> None:
            _fire()

        try:
            kbd = keyboard.Listener(on_press=on_press)
            ptr = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
            kbd.start()
            ptr.start()
        except Exception as exc:
            # macOS sans autorisation Accessibilité : échec visible, pas de fallback.
            self._error = (
                "Autorisation refusée (macOS : Réglages > Confidentialité et sécurité > "
                f"Accessibilité) : {exc}"
            )
            logger.error("Flux d'activité impossible : %s", self._error)
            try:
                kbd.stop()
            except Exception:
                pass
            return False

        # Vérification explicite des autorisations macOS : si elles manquent,
        # le flux ne tourne pas — on signale l'état réel (DEGRADED) plutôt que
        # de prétendre à une écoute active. Après accord de la permission,
        # redémarrer le module (page Modules) relancera l'écoute.
        allowed, permission_message = macos_input_permissions()
        if not allowed:
            for item in (kbd, ptr):
                try:
                    item.stop()
                except Exception:
                    pass
            with self._lock:
                self._active = False
                self._error = permission_message
            logger.warning("Flux d'activité démarrage refusé : %s", permission_message)
            return False

        self._listener = (kbd, ptr)
        with self._lock:
            self._active = True
            self._error = ""
        logger.info("Flux d'activité pynput démarré (aucun contenu enregistré).")
        return True

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
            self._active = False
            self._on_activity = None
        if listener:
            for item in listener:
                try:
                    item.stop()
                except Exception:
                    logger.exception("Erreur à l'arrêt du listener pynput.")

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def last_error(self) -> str:
        return self._error


class SyntheticActivityStream(ActivityStream):
    """Flux de test : pilotable manuellement (utilisé par les tests unitaires)."""

    name = "synthetic"

    def __init__(self) -> None:
        self._cb: ActivityCallback | None = None
        self._active = False

    def start(self, on_activity: ActivityCallback) -> bool:
        self._cb = on_activity
        self._active = True
        return True

    def stop(self) -> None:
        self._active = False
        self._cb = None

    @property
    def active(self) -> bool:
        return self._active

    def inject(self) -> None:
        """Simule une activité utilisateur (tests uniquement)."""
        if self._cb:
            self._cb()
