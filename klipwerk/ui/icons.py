"""Inline SVG icon templates and a helper to render them as QIcons.

Templates use ``{color}`` as a placeholder so the same shape can be
recolored for hover states. :func:`make_icon` caches results per
(template-id, color, size) triple — previously every hover would
re-parse and re-render the SVG on every mouse-enter.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

SVG_DOWNLOAD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M8 12L3 7h3V2h4v5h3L8 12z" fill="{color}"/>
  <rect x="2" y="13" width="12" height="1.5" rx="0.75" fill="{color}"/>
</svg>"""

SVG_LAYERS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M8 1L1 5l7 4 7-4-7-4z" fill="{color}"/>
  <path d="M1 9l7 4 7-4" stroke="{color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
  <path d="M1 12l7 4 7-4" stroke="{color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
</svg>"""

SVG_CLIP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="1" y="2" width="14" height="12" rx="1.5" stroke="{color}" stroke-width="1.5" fill="none"/>
  <path d="M5 2v12M1 6h4M1 10h4" stroke="{color}" stroke-width="1.2" stroke-linecap="round"/>
  <circle cx="11" cy="8" r="2.5" stroke="{color}" stroke-width="1.5" fill="none"/>
  <path d="M13 10l2 2" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>
</svg>"""

SVG_MINIMIZE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="3" y="7.5" width="10" height="1.5" rx="0.75" fill="{color}"/>
</svg>"""

SVG_MAXIMIZE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="3" y="3" width="10" height="10" rx="1" stroke="{color}" stroke-width="1.5" fill="none"/>
</svg>"""

SVG_RESTORE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="5" y="3" width="8" height="8" rx="1" stroke="{color}" stroke-width="1.4" fill="none"/>
  <path d="M3 6v7h7" stroke="{color}" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

SVG_CLOSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M3 3l10 10M13 3L3 13" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>
</svg>"""


@lru_cache(maxsize=128)
def make_icon(svg_template: str, color: str, size: int = 16) -> QIcon:
    """Render *svg_template* with ``{color}`` substituted as a QIcon.

    Results are cached — the same (template, color, size) combination
    will reuse the existing pixmap instead of re-parsing the SVG.
    """
    svg_bytes = svg_template.replace("{color}", color).encode()
    renderer = QSvgRenderer(svg_bytes)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pixmap)
