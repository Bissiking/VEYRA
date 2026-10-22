# veyra/storage/config.py
"""Configuration persistante de VEYRA (couche au-dessus de SQLite)."""

from __future__ import annotations

import json
import logging
from typing import Any

from veyra.core.policy import SecurityPolicy
from veyra.storage.database import Database

logger = logging.getLogger(__name__)

_PREFIX = "config."
_MODE_KEY = "protection_mode"


class ConfigStore:
    """Lit/écrit les paramètres de l'application dans la table ``settings``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------ généraux

    def get_raw(self, key: str, default: Any = None) -> Any:
        value = self._db.get_setting(_PREFIX + key)
        if value is None:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def set_raw(self, key: str, value: Any) -> None:
        self._db.set_setting(_PREFIX + key, json.dumps(value))

    # ------------------------------------------------------------ politique

    def load_policy(self) -> SecurityPolicy:
        data = self.get_raw("policy", default={})
        if not isinstance(data, dict):
            data = {}
        return SecurityPolicy.from_dict(data)

    def save_policy(self, policy: SecurityPolicy) -> None:
        self.set_raw("policy", policy.to_dict())

    # ------------------------------------------------------- paramètres GUI

    def get_camera_index(self) -> int:
        value = self.get_raw("camera_index", default=0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def set_camera_index(self, index: int) -> None:
        self.set_raw("camera_index", int(index))

    def get_keep_raw_images(self) -> bool:
        """V0.1 : False par défaut ; l'enregistrement d'images n'est pas implémenté."""
        return bool(self.get_raw("keep_raw_images", default=False))

    def set_keep_raw_images(self, value: bool) -> None:
        self.set_raw("keep_raw_images", bool(value))

    def get_low_power(self) -> bool:
        """Baisse la cadence d'analyse pour économiser le CPU."""
        return bool(self.get_raw("low_power", default=False))

    def set_low_power(self, value: bool) -> None:
        self.set_raw("low_power", bool(value))

    # --------------------------------------------------- dernier mode lu

    def get_last_protection_mode(self) -> str:
        """Retourne le dernier mode enregistré.

        NOTE : au démarrage, l'application force TOUJOURS la SIMULATION ;
        cette valeur ne sert qu'au rappel dans l'interface.
        """
        value = self._db.get_setting(_MODE_KEY)
        return value or "SIMULATION"

    def set_protection_mode(self, mode: str) -> None:
        self._db.set_setting(_MODE_KEY, mode)
