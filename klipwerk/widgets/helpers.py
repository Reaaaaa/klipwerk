"""Small helpers for building up the UI: styled labels, buttons, separators."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from ..ui.theme import BORDER, BORDER2, MUTED2, TEXT


def btn(
    text: str,
    *,
    accent: bool = False,
    danger: bool = False,
    compact: bool = False,
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a QPushButton with our standard accent/danger styling.

    ``compact=True`` tags the button with a ``compact`` object name so
    the global stylesheet can render it slimmer — used for toolbar
    buttons that need to line up with the C/K and Tips toggles visually.
    ``compact`` can combine with ``danger`` via a multi-class selector
    (``#danger.compact`` doesn't work on plain ObjectNames, so we use
    a property instead — see theme.py).
    """
    button = QPushButton(text, parent)
    if accent:
        button.setObjectName("accent")
    elif danger:
        button.setObjectName("danger")
    if compact:
        # Property-based selector works alongside object names, so a
        # `danger` button can also be `compact`.
        button.setProperty("compact", True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def label(
    text: str,
    *,
    color: str = TEXT,
    bold: bool = False,
    size: int = 13,
) -> QLabel:
    """Create a styled QLabel with our preferred font size / weight."""
    lbl = QLabel(text)
    style = f"color:{color}; font-size:{size}px;"
    if bold:
        style += "font-weight:bold;"
    lbl.setStyleSheet(style)
    return lbl


def hsep() -> QFrame:
    """A thin horizontal divider used between sidebar sections."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setStyleSheet(f"color:{BORDER2}; margin: 2px 0;")
    return frame


def section_label(text: str) -> QLabel:
    """An ALL-CAPS muted section header."""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color:{MUTED2}; font-size:10px; letter-spacing:2px; "
        f"font-weight:bold; padding: 2px 0;"
    )
    return lbl


__all__ = ["BORDER", "btn", "hsep", "label", "section_label"]
