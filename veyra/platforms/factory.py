# veyra/platforms/factory.py
"""Fabrique d'adaptateur plateforme selon l'hôte courant."""

from __future__ import annotations

import sys

from veyra.platforms.base import PlatformAdapter
from veyra.platforms.linux import LinuxAdapter
from veyra.platforms.macos import MacosAdapter
from veyra.platforms.windows import WindowsAdapter


def create_platform_adapter() -> PlatformAdapter:
    if sys.platform == "darwin":
        return MacosAdapter()
    if sys.platform.startswith("win"):
        return WindowsAdapter()
    return LinuxAdapter()
