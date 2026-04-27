"""User-preference persistence via Qt's ``QSettings``.

Anything that should survive a restart lives here: window geometry,
export defaults (format/crf/preset/prefix/suffix), and the K/C language
toggle. The rest of the app stays unaware of ``QSettings`` — it asks
:class:`Settings` for a typed value and gets a safe default on any
parse error or missing key.

On real systems this persists to:

* Linux   — ``~/.config/Klipwerk/Klipwerk.conf``
* Windows — registry ``HKCU\\Software\\Klipwerk\\Klipwerk``
* macOS   — ``~/Library/Preferences/com.Klipwerk.Klipwerk.plist``

Tests can construct ``Settings(path="/tmp/foo.ini")`` to opt out of the
platform-native storage and use a throwaway ini file instead.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QByteArray, QSettings

ORG = "Klipwerk"
APP = "Klipwerk"

# Key names — kept as module constants so typos fail at import time, not
# at runtime when a user closes the window.
K_GEOMETRY      = "window/geometry"
K_FMT_INDEX     = "export/fmt_index"
K_CRF           = "export/crf"
K_PRESET        = "export/preset"
K_PREFIX        = "export/prefix"
K_SUFFIX        = "export/suffix"
K_SUFFIX_CROP   = "export/suffix_crop"
K_SUFFIX_CLIP   = "export/suffix_clip"
K_SUFFIX_SEQ    = "export/suffix_seq"
K_USE_K_MODE    = "ui/use_k_mode"
K_SIDEBAR_SPLIT = "ui/sidebar_splitter"
K_GIF_FPS       = "gif/fps"
K_GIF_WIDTH     = "gif/width"


class Settings:
    """Thin typed facade over :class:`QSettings`.

    All getters take a default. Any parse/type failure falls back to
    that default rather than raising — a malformed settings file must
    never keep the app from launching.
    """

    def __init__(self, path: str | None = None) -> None:
        if path is None:
            self._qs = QSettings(ORG, APP)
        else:
            self._qs = QSettings(path, QSettings.Format.IniFormat)

    # ── Generic helpers ────────────────────────────────────────────
    def _get(self, key: str, default: Any, type_: type) -> Any:
        """``QSettings.value`` with a typed fallback on any error."""
        if not self._qs.contains(key):
            return default
        try:
            val = self._qs.value(key, default, type=type_)
        except (TypeError, ValueError):
            return default
        # Qt sometimes hands back the default as-is on type mismatch;
        # be defensive so callers always get the declared type.
        if not isinstance(val, type_):
            return default
        return val

    def _set(self, key: str, value: Any) -> None:
        self._qs.setValue(key, value)

    # ── Geometry (opaque Qt blob) ──────────────────────────────────
    def geometry(self) -> QByteArray | None:
        """Return saved geometry blob, or ``None`` if never written."""
        if not self._qs.contains(K_GEOMETRY):
            return None
        val = self._qs.value(K_GEOMETRY)
        if isinstance(val, QByteArray) and not val.isEmpty():
            return val
        return None

    def set_geometry(self, blob: QByteArray) -> None:
        self._set(K_GEOMETRY, blob)

    # ── Export preferences ─────────────────────────────────────────
    def fmt_index(self, default: int = 0) -> int:
        idx = self._get(K_FMT_INDEX, default, int)
        # Gets validated by caller against the real FORMATS list.
        return idx

    def set_fmt_index(self, idx: int) -> None:
        self._set(K_FMT_INDEX, int(idx))

    def crf(self, default: int) -> int:
        return self._get(K_CRF, default, int)

    def set_crf(self, v: int) -> None:
        self._set(K_CRF, int(v))

    def preset(self, default: str = "") -> str:
        return self._get(K_PRESET, default, str)

    def set_preset(self, v: str) -> None:
        self._set(K_PRESET, str(v))

    def prefix(self, default: str = "") -> str:
        return self._get(K_PREFIX, default, str)

    def set_prefix(self, v: str) -> None:
        self._set(K_PREFIX, str(v))

    def suffix(self, default: str = "_crop") -> str:
        return self._get(K_SUFFIX, default, str)

    def set_suffix(self, v: str) -> None:
        self._set(K_SUFFIX, str(v))

    def suffix_crop(self, default: str = "_crop") -> str:
        return self._get(K_SUFFIX_CROP, default, str)

    def set_suffix_crop(self, v: str) -> None:
        self._set(K_SUFFIX_CROP, str(v))

    def suffix_clip(self, default: str = "_clip") -> str:
        return self._get(K_SUFFIX_CLIP, default, str)

    def set_suffix_clip(self, v: str) -> None:
        self._set(K_SUFFIX_CLIP, str(v))

    def suffix_seq(self, default: str = "_seq") -> str:
        return self._get(K_SUFFIX_SEQ, default, str)

    def set_suffix_seq(self, v: str) -> None:
        self._set(K_SUFFIX_SEQ, str(v))

    # ── UI toggles ─────────────────────────────────────────────────
    def use_k_mode(self, default: bool = True) -> bool:
        return self._get(K_USE_K_MODE, default, bool)

    def set_use_k_mode(self, v: bool) -> None:
        self._set(K_USE_K_MODE, bool(v))

    # Opaque Qt blob (QSplitter.saveState). Mirrors geometry() pattern:
    # None means "never written", anything else is replayed as-is.
    def sidebar_splitter(self) -> QByteArray | None:
        if not self._qs.contains(K_SIDEBAR_SPLIT):
            return None
        val = self._qs.value(K_SIDEBAR_SPLIT)
        if isinstance(val, QByteArray) and not val.isEmpty():
            return val
        return None

    def set_sidebar_splitter(self, blob: QByteArray) -> None:
        self._set(K_SIDEBAR_SPLIT, blob)

    # ── GIF export preferences ─────────────────────────────────────
    def gif_fps(self, default: int = 12) -> int:
        """Last-used GIF frame rate (8 / 12 / 15 / 24)."""
        return self._get(K_GIF_FPS, default, int)

    def set_gif_fps(self, v: int) -> None:
        self._set(K_GIF_FPS, int(v))

    def gif_width(self, default: int = 0) -> int:
        """Last-used GIF output width in pixels; 0 means original size."""
        return self._get(K_GIF_WIDTH, default, int)

    def set_gif_width(self, v: int) -> None:
        self._set(K_GIF_WIDTH, int(v))

    # ── Misc ───────────────────────────────────────────────────────
    def sync(self) -> None:
        """Force write-through to disk. Normally unnecessary."""
        self._qs.sync()

    @property
    def path(self) -> str:
        return self._qs.fileName()
