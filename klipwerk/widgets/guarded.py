"""Scroll-safe subclasses of QComboBox / QSpinBox / QDoubleSpinBox.

The default Qt behavior is that a spinbox or combobox will steal the
mouse wheel the moment it's under the cursor — which is fantastic when
you're filling in a form and terrible when you're scrolling a sidebar
full of them. These variants only accept wheel events after the user
has explicitly clicked the widget to focus it.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class _NoScrollUnfocused:
    """Mixin: ignore mouse wheel unless user explicitly clicked first."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._click_focused = False
        # StrongFocus keeps keyboard navigation working; we gate wheel ourselves.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._click_focused = True
        super().mousePressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._click_focused = False
        super().focusOutEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        # Only enable wheel after an actual mouse click — not when the
        # focus arrived via Tab or the window reactivating.
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            self._click_focused = True
        elif event.reason() != Qt.FocusReason.ActiveWindowFocusReason:
            self._click_focused = False
        super().focusInEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._click_focused:
            super().wheelEvent(event)
        else:
            event.ignore()


class GuardedSpinBox(_NoScrollUnfocused, QSpinBox):
    """QSpinBox that won't steal wheel events from the surrounding area."""


class GuardedDoubleSpinBox(_NoScrollUnfocused, QDoubleSpinBox):
    """QDoubleSpinBox that won't steal wheel events from the surrounding area."""


class GuardedComboBox(_NoScrollUnfocused, QComboBox):
    """QComboBox that won't steal wheel events from the surrounding area."""
