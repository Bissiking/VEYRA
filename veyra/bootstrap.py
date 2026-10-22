# veyra/bootstrap.py
"""Assemblage de l'application VEYRA (composition, sans service externe).

Chaque partie est créée ici puis connectée :
bus -> modules -> moteur -> session_guard -> exécuteur -> plateforme.
Le mode de protection repose TOUJOURS en SIMULATION à ce niveau ;
seule la GUI peut demander la bascule PROTECTION avec confirmation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from veyra.core.engine import SurveillanceEngine
from veyra.core.events import EventBus
from veyra.core.module_manager import ModuleManager
from veyra.core.policy import ProtectionMode, SecurityPolicy
from veyra.core.safety import ActionExecutor, SafetyCircuit
from veyra.modules.activity_guard.module import ActivityGuardModule
from veyra.modules.face_guard.enrollment import EnrollmentSession, ProfileRepository
from veyra.modules.face_guard.module import FaceGuardModule
from veyra.modules.session_guard.module import SessionGuardModule
from veyra.platforms.base import PlatformAdapter
from veyra.platforms.factory import create_platform_adapter
from veyra.storage.biometrics import BiometricVault, create_key_storage
from veyra.storage.config import ConfigStore
from veyra.storage.database import Database
from veyra.storage.event_store import EventStore

logger = logging.getLogger(__name__)


class AppContext:
    """Conteneur des services VEYRA pour la durée de vie de l'application."""

    def __init__(self, db_path: Path | str) -> None:
        # Infrastructure
        self.bus = EventBus()
        self.db = Database(db_path)
        self.config = ConfigStore(self.db)
        self.event_store = EventStore(self.bus, self.db)
        self.policy: SecurityPolicy = self.config.load_policy()

        # Plateforme + coupe-circuit
        self.platform: PlatformAdapter = create_platform_adapter()
        self.circuit = SafetyCircuit(self.bus)  # mode SIMULATION par construction
        self.executor = ActionExecutor(self.circuit, self.platform, self.bus)

        # Biométrie (coffre clés de la plateforme)
        self.vault = BiometricVault(create_key_storage())
        self.profile_repo = ProfileRepository(self.db, self.vault)
        self.enrollment = EnrollmentSession(
            policy=self.policy,
            pipeline=None,  # renseigné par FaceGuardModule ci-dessous
            vault=self.vault,
            db=self.db,
            bus=self.bus,
        )

        # Modules
        self.face_guard = FaceGuardModule(
            bus=self.bus,
            policy=self.policy,
            profile_repo=self.profile_repo,
            enrollment=self.enrollment,
            camera_index=self.config.get_camera_index(),
        )
        # L'enrôlement partage le pipeline chargé par le module (même instance).
        self.enrollment.pipeline = self.face_guard.pipeline

        self.activity_guard = ActivityGuardModule(self.bus, self.platform)
        self.session_guard = SessionGuardModule(self.bus, self.executor)

        self.modules = ModuleManager(self.bus)
        self.modules.register(self.face_guard)
        self.modules.register(self.activity_guard)
        self.modules.register(self.session_guard)

        # Moteur de décision
        self.engine = SurveillanceEngine(self.bus, self.policy)

        # Performance
        self.face_guard.set_low_power(self.config.get_low_power())

        logger.info("Contexte VEYRA assemblé (mode=%s).", self.circuit.mode.value)

    # ----------------------------------------------------------- cycle de vie

    def start(self) -> None:
        """Démarre le moteur et tous les modules (la GUI n'est pas concernée)."""
        self.engine.start()
        self.modules.start_all()
        logger.info("VEYRA démarré — protection en mode %s.",
                    self.circuit.mode.value)

    def stop(self) -> None:
        self.modules.stop_all()
        self.engine.stop()
        self.event_store.close()
        self.db.close()
        logger.info("VEYRA arrêté.")

    # ------------------------------------------------------ actions GUI

    def enable_protection(self, confirmed: bool) -> bool:
        """Bascule PROTECTION (confirmation explicite obligatoire)."""
        ok = self.circuit.enable_protection(confirmed)
        if ok:
            self.config.set_protection_mode(ProtectionMode.PROTECTION.value)
        return ok

    def revert_to_simulation(self) -> None:
        self.circuit.revert_to_simulation()
        self.config.set_protection_mode(ProtectionMode.SIMULATION.value)

    def apply_policy(self, policy: SecurityPolicy) -> None:
        """Applique une politique modifiée (GUI Settings) en cours d'exécution."""
        self.policy = policy
        self.config.save_policy(policy)
        self.engine.update_policy(policy)
        self.face_guard.set_policy(policy)
        self.enrollment.policy = policy

    def delete_biometric_profile(self) -> bool:
        """Suppression complète du profil biométrique (+ clé Keychain)."""
        deleted = self.profile_repo.delete_profile()
        try:
            self.profile_repo.destroy_vault()
        except Exception:
            logger.exception("Effacement de la clé Keychain partiellement échoué.")
        logger.info("Profil biométrique supprimé (ligne=%s, clé effacée).", deleted)
        return deleted
