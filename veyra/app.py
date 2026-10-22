# veyra/app.py
"""Point d'entrée de l'application VEYRA.

Responsabilités :
- configuration du logging structuré (fichier + console, sans données sensibles) ;
- construction du contexte (``AppContext``) et démarrage du noyau ;
- lancement de la boucle d'événements Qt.

Le mode de protection est TOUJOURS SIMULATION au démarrage (V0.1).
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from veyra import __version__


def _default_data_dir() -> Path:
    """Dossier de données utilisateur (macOS/Linux) sans privilèges admin."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VEYRA"
    if sys.platform.startswith("win"):
        base = Path.home() / "AppData" / "Local"
        return base / "VEYRA"
    base = Path.home() / ".local" / "share"
    return base / "veyra"


def setup_logging(data_dir: Path, verbose: bool = False) -> None:
    """Logging structuré : journal texte horodaté fichier + console.

    Ne journalise jamais d'empreintes, d'images ou de contenus de frappe.
    """
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "veyra.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    # Réduit le bruit des bibliothèques tierces
    logging.getLogger("pynput").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="veyra",
        description=f"VEYRA {__version__} — plateforme de sécurité locale.",
    )
    parser.add_argument("--db", type=Path, default=None,
                        help="Chemin de la base SQLite (défaut : données utilisateur).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Journaux détaillés (console en DEBUG).")
    parser.add_argument("--version", action="version",
                        version=f"VEYRA {__version__}")
    args = parser.parse_args(argv)

    data_dir = _default_data_dir()
    setup_logging(data_dir, verbose=args.verbose)
    logger = logging.getLogger("veyra")
    logger.info("Démarrage de VEYRA %s (mode SIMULATION forcé).", __version__)

    db_path = args.db or (data_dir / "veyra.db")

    from veyra.bootstrap import AppContext

    ctx = AppContext(db_path)
    # Sécurité V0.1 : TOUJOURS démarrer en simulation.
    ctx.revert_to_simulation()

    from PySide6.QtWidgets import QApplication

    from veyra.gui import theme
    from veyra.gui.bridge import GuiBridge
    from veyra.gui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("VEYRA")
    app.setOrganizationName("VEYRA")
    app.setQuitOnLastWindowClosed(False)  # le tray pilote la fermeture
    theme.apply_theme(app)
    app.setWindowIcon(theme.make_app_icon())

    bridge = GuiBridge(ctx.bus)
    window = MainWindow(ctx, bridge)
    window.show()

    ctx.start()

    exit_code = 0
    try:
        exit_code = app.exec()
    except KeyboardInterrupt:
        logger.info("Interruption clavier.")
    finally:
        logger.info("Arrêt de VEYRA…")
        bridge.shutdown()
        window.hide()
        ctx.stop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
