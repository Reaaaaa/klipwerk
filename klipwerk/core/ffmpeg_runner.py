"""Locate the ffmpeg / ffprobe binaries and provide platform-safe
subprocess flags.

Two bugs fixed vs. the original monolithic script:

1. ``BASE`` was referenced but never defined, so the fallback branch of
   ``find_bin`` would crash with ``NameError`` whenever ffmpeg was not
   on ``$PATH``.
2. ``subprocess.CREATE_NO_WINDOW`` only exists on Windows — referencing
   it on Linux/macOS raises ``AttributeError`` even inside a ternary,
   because Python evaluates both branches. We gate the lookup behind
   ``getattr`` and expose a module-level constant to use everywhere.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Directory this package lives in — used for bundled ffmpeg binaries.
# Two parents up: klipwerk/core/ffmpeg_runner.py  ->  klipwerk/  ->  repo root.
BASE: Path = Path(__file__).resolve().parent.parent

# Subprocess flag to hide console windows on Windows. 0 everywhere else.
# ``getattr`` avoids AttributeError on non-Windows platforms where the
# constant simply does not exist.
CREATION_FLAGS: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_FFMPEG: str | None = None
_FFPROBE: str | None = None


def _candidates(name: str) -> list[Path]:
    """Return the search order for a given binary name."""
    exe = ".exe" if sys.platform == "win32" else ""
    base_name = f"{name}{exe}"
    return [
        BASE / base_name,
        BASE / "bin" / base_name,
        BASE.parent / base_name,        # repo-root/ffmpeg.exe layout
        BASE.parent / "bin" / base_name,
        Path.home() / "Documents" / "ffmpeg" / base_name,
        Path(r"C:\ffmpeg\bin") / base_name,
        Path(r"C:\Program Files\ffmpeg\bin") / base_name,
    ]


def find_bin(name: str) -> str:
    """Locate *name* on PATH or in one of the known fallback locations.

    Raises ``FileNotFoundError`` with a user-friendly message if nothing
    matches. Always returns an absolute path string.
    """
    found = shutil.which(name)
    if found:
        return found

    for candidate in _candidates(name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise FileNotFoundError(
        f"'{name}' nicht gefunden!\n"
        f"Leg {name} neben klipwerk.py oder füg ffmpeg zum PATH hinzu.\n"
        f"Download: https://www.gyan.dev/ffmpeg/builds/"
    )


def resolve_binaries() -> tuple[str, str]:
    """Find both ffmpeg and ffprobe, caching the result.

    Called once at startup. Subsequent calls via :func:`ffmpeg_bin` /
    :func:`ffprobe_bin` are free.
    """
    global _FFMPEG, _FFPROBE
    _FFMPEG = find_bin("ffmpeg")
    _FFPROBE = find_bin("ffprobe")
    log.info("ffmpeg: %s", _FFMPEG)
    log.info("ffprobe: %s", _FFPROBE)
    return _FFMPEG, _FFPROBE


def ffmpeg_bin() -> str:
    if _FFMPEG is None:
        resolve_binaries()
    return _FFMPEG  # type: ignore[return-value]


def ffprobe_bin() -> str:
    if _FFPROBE is None:
        resolve_binaries()
    return _FFPROBE  # type: ignore[return-value]
