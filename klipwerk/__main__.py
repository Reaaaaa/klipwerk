"""Klipwerk entry point.

Launches the main window. Executed via `python -m klipwerk` or the
`klipwerk` console script registered in pyproject.toml.
"""
from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .core import ffmpeg_runner
from .ui.theme import BORDER2

log = logging.getLogger(__name__)


def main() -> int:
    # Cheap flag handling *before* we touch Qt — spinning up a
    # QApplication just to print a version string would be wasteful and
    # would fail on headless boxes without a display server.
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print(f"Klipwerk {__version__}")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(
            "Klipwerk — desktop video editor\n"
            "\n"
            "Usage: klipwerk [OPTIONS]\n"
            "\n"
            "Options:\n"
            "  --version, -V         Print version and exit\n"
            "  --help, -h            Show this help\n"
            "  --reset-settings      Delete saved settings (geometry,\n"
            "                        splitter position, export defaults)\n"
            "                        and start fresh\n"
            "\n"
            "Without arguments, launches the main window."
        )
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "--reset-settings":
        # Construct a QSettings with the right organization/app names
        # and call clear(). This works even if the ini file is
        # corrupt — QSettings just overwrites it.
        from PyQt6.QtCore import QSettings
        QSettings("Klipwerk", "Klipwerk").clear()
        print("Klipwerk: settings reset.")
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Klipwerk")
    app.setOrganizationName("Klipwerk")

    # Resolve ffmpeg/ffprobe before we build the UI — if it fails we want
    # to show a clean dialog and quit without half-building a window.
    try:
        ffmpeg_runner.resolve_binaries()
    except FileNotFoundError as exc:
        QMessageBox.critical(None, "Klipwerk — ffmpeg fehlt", str(exc))
        return 1

    # Import app lazily so the ffmpeg check runs first
    from .app import Klipwerk

    win = Klipwerk()

    screen = app.primaryScreen().availableGeometry()
    w = int(screen.width() * 0.75)
    h = int(screen.height() * 0.75)
    win.resize(w, h)
    win.move(
        screen.x() + (screen.width() - w) // 2,
        screen.y() + (screen.height() - h) // 2,
    )
    win.setStyleSheet(
        win.styleSheet() + f"QMainWindow {{ border: 1px solid {BORDER2}; }}"
    )
    win.show()
    win._refresh_klip_labels()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
