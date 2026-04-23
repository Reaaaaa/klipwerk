"""Clip list entry and timeline tile widgets.

``ClipItem`` renders a vertical list row in the sidebar; ``TimelineClip``
renders a horizontal tile in the bottom timeline. Both emit signals
keyed by the clip's index, which the parent uses to route into the
shared clip list.
"""
from __future__ import annotations

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QDrag, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..core.models import Clip
from ..ui.theme import ACC, ACC3, BORDER, BORDER2, MUTED, MUTED2, S2, S3, TEXT
from .helpers import label


class ClipItem(QFrame):
    """A single clip row in the sidebar list."""

    selected = pyqtSignal(int)
    deleted  = pyqtSignal(int)
    renamed  = pyqtSignal(int)   # triggered on double-click

    def __init__(self, clip: Clip, index: int, duration: float):
        super().__init__()
        self.index = index
        self.setObjectName("clipItem")
        self._base_style = (
            f"QFrame#clipItem {{ background:{S2}; border:1px solid {BORDER};"
            f" border-radius:5px; padding:2px; }}"
            f"QFrame#clipItem:hover {{ border-color:{BORDER2}; }}"
        )
        self.setStyleSheet(self._base_style)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(3)

        # Header: name + delete button
        header = QHBoxLayout()
        name_lbl = label(clip.name, bold=True, size=11)
        name_lbl.setStyleSheet(
            f"color:{TEXT}; font-weight:bold; font-size:11px; background:transparent;"
        )
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(18, 18)
        del_btn.setStyleSheet(
            f"background:none; border:none; color:{MUTED}; font-size:10px; padding:0;"
        )
        del_btn.clicked.connect(lambda: self.deleted.emit(self.index))
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.addWidget(name_lbl)
        header.addStretch()
        header.addWidget(del_btn)

        dur = clip.duration
        time_lbl = label(
            f"{clip.start:.2f}s → {clip.end:.2f}s  ({dur:.2f}s)",
            color=MUTED2, size=10,
        )

        # Progress bar — how long this clip is relative to the full video
        bar = QFrame()
        bar.setFixedHeight(2)
        bar.setStyleSheet(f"background:{BORDER}; border-radius:1px;")
        pct = int(dur / duration * 100) if duration else 0
        fill = QFrame(bar)
        fill.setFixedHeight(2)
        fill.setFixedWidth(max(2, int(pct * 1.4)))
        fill.setStyleSheet(f"background:{ACC}; border-radius:1px;")

        layout.addLayout(header)
        layout.addWidget(time_lbl)
        if clip.crop:
            layout.addWidget(
                label(f"✂  {clip.crop['w']}×{clip.crop['h']}", color=ACC3, size=10)
            )
        layout.addWidget(bar)

    def set_active(self, active: bool) -> None:
        color = ACC if active else BORDER
        self.setStyleSheet(
            f"QFrame#clipItem {{ background:{S2}; border:1px solid {color};"
            f" border-radius:5px; padding:2px; }}"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.index)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.renamed.emit(self.index)


class TimelineClip(QFrame):
    """A horizontal tile in the bottom timeline. Supports drag-to-reorder."""

    clicked   = pyqtSignal(int)
    moved     = pyqtSignal(int, int)   # (from_index, to_index)
    previewed = pyqtSignal(int)
    renamed   = pyqtSignal(int)

    def __init__(self, clip: Clip, index: int, width: int):
        super().__init__()
        self.index = index
        self.setObjectName("tc")
        self.setFixedSize(max(70, width), 56)
        self.setStyleSheet(
            f"QFrame#tc {{ background:{S2}; border:1px solid {BORDER};"
            f" border-radius:5px; }}"
        )
        self.setAcceptDrops(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        # Top row: name + mini play button
        top = QHBoxLayout()
        top.setSpacing(3)
        top.setContentsMargins(0, 0, 0, 0)

        name = QLabel(clip.name)
        name.setStyleSheet(f"color:{TEXT}; font-size:10px; background:transparent;")
        name.setMinimumWidth(0)

        play_btn = QPushButton("▶")
        play_btn.setFixedSize(16, 16)
        play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        play_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        play_btn.setStyleSheet(
            f"QPushButton {{ background:{S3}; border:1px solid {BORDER2};"
            f" color:{ACC}; font-size:8px; border-radius:3px; padding:0; }}"
            f"QPushButton:hover {{ background:{ACC}; color:#000; border-color:{ACC}; }}"
        )
        play_btn.clicked.connect(lambda: self.previewed.emit(self.index))
        top.addWidget(name, 1)
        top.addWidget(play_btn)

        dur_lbl = QLabel(f"{clip.duration:.1f}s")
        dur_lbl.setStyleSheet(
            f"color:{MUTED2}; font-size:9px; background:transparent;"
        )

        bar = QFrame()
        bar.setFixedHeight(2)
        bar.setStyleSheet(f"background:{ACC}; border-radius:1px;")

        layout.addLayout(top)
        layout.addWidget(dur_lbl)
        layout.addStretch()
        layout.addWidget(bar)

    def set_active(self, active: bool) -> None:
        color = ACC if active else BORDER
        self.setStyleSheet(
            f"QFrame#tc {{ background:{S2}; border:1px solid {color};"
            f" border-radius:5px; }}"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.clicked.emit(self.index)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.index))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.renamed.emit(self.index)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        try:
            from_idx = int(event.mimeData().text())
        except ValueError:
            return
        if from_idx == self.index:
            return   # dropped on itself — no-op
        self.moved.emit(from_idx, self.index)
