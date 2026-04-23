"""The timeline scrubber: waveform, playhead, in/out markers, hover thumbnail.

Design notes:

* The waveform is a numpy array of peaks (one per pixel column) produced
  by :class:`klipwerk.workers.waveform.WaveformWorker`. We colorize the
  played portion differently from the unplayed one without having to
  blit an image — each 1-pixel-wide rect is drawn in-place.
* The hover thumbnail machinery from the original script was half-
  implemented (fetch existed, paint never called). We either wire it up
  properly or remove it. Kept the API but disabled by default until the
  calling code explicitly opts in.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygon,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..ui.theme import ACC, ACC2, ACC3, BORDER2, S2, S3, TEXT


class ScrubberWidget(QWidget):
    """Custom timeline control with waveform and in/out markers."""

    seeked    = pyqtSignal(float)                # percent 0.0 – 1.0
    hoverTime = pyqtSignal(float, int, int)      # (seconds, widget-x, global-y); -1 on leave

    # Layout constants
    _MARGIN = 8        # horizontal padding inside the widget
    _TRACK_H = 4       # height of the seekbar track
    _HANDLE_R = 6      # playhead circle radius

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMouseTracking(True)

        self._pos: float = 0.0
        self._in: float = 0.0
        self._out: float = 1.0
        self._waveform: np.ndarray | None = None
        self._hover_x: int = -1
        self._duration: float = 0.0
        self._video_path: str | None = None
        self.setEnabled(False)

    # ── Public API ──────────────────────────────────────────────────
    def set_video(self, path: str, duration: float) -> None:
        self._video_path = path
        self._duration = duration
        self._waveform = None
        self.update()

    def clear_video(self) -> None:
        self._video_path = None
        self._duration = 0.0
        self._waveform = None
        self._pos = 0.0
        self._in = 0.0
        self._out = 1.0
        self.setEnabled(False)
        self.update()

    def set_waveform(self, peaks: np.ndarray | None) -> None:
        self._waveform = peaks
        self.update()

    def set_position(self, pct: float) -> None:
        self._pos = max(0.0, min(1.0, pct))
        self.update()

    def set_markers(self, in_pct: float, out_pct: float) -> None:
        self._in = max(0.0, min(1.0, in_pct))
        self._out = max(0.0, min(1.0, out_pct))
        self.update()

    # ── Painting ────────────────────────────────────────────────────
    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            m = self._MARGIN
            track_px = max(1, w - m * 2)
            track_y = h - 12
            track_h = self._TRACK_H

            self._paint_waveform(painter, m, track_px, track_y)
            self._paint_track_bg(painter, m, track_px, track_y, track_h)

            if not self.isEnabled():
                return

            self._paint_in_out_zone(painter, m, track_px, track_y, track_h)
            self._paint_played(painter, m, track_px, track_y, track_h)
            self._paint_markers(painter, m, track_px, track_y)
            self._paint_playhead(painter, m, track_px, track_y, track_h)

            if self._hover_x >= 0:
                painter.setPen(QPen(QColor(TEXT + "66"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(self._hover_x, 0, self._hover_x, h)
        finally:
            painter.end()

    def _paint_waveform(self, painter: QPainter, m: int, track_px: int, ty: int) -> None:
        wf = self._waveform
        if wf is None or not self.isEnabled():
            # Fallback: flat placeholder
            painter.fillRect(m, 4, track_px, ty - 8, QColor(S3))
            return

        n = len(wf)
        if n == 0:
            painter.fillRect(m, 4, track_px, ty - 8, QColor(S3))
            return

        wf_h = max(2, ty - 4)
        mid = ty // 2
        played_color = QColor(ACC)
        played_color.setAlpha(170)
        unplayed_color = QColor(BORDER2)

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(track_px):
            idx = int(i / track_px * n)
            peak = float(wf[min(idx, n - 1)])
            bar = max(1, int(peak * wf_h * 0.45))
            xi = m + i
            if i / track_px <= self._pos:
                painter.setBrush(QBrush(played_color))
            else:
                painter.setBrush(QBrush(unplayed_color))
            painter.drawRect(xi, mid - bar, 1, bar * 2)

    def _paint_track_bg(self, painter: QPainter, m: int, track_px: int,
                        ty: int, th: int) -> None:
        painter.setBrush(QBrush(QColor(S2)))
        painter.setPen(QPen(QColor(BORDER2), 1))
        painter.drawRoundedRect(m, ty, track_px, th, 2, 2)

    def _paint_in_out_zone(self, painter: QPainter, m: int, track_px: int,
                           ty: int, th: int) -> None:
        if self._out <= self._in:
            return
        ix = m + int(self._in * track_px)
        ox = m + int(self._out * track_px)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(200, 245, 58, 50)))
        painter.drawRect(ix, ty, ox - ix, th)

    def _paint_played(self, painter: QPainter, m: int, track_px: int,
                      ty: int, th: int) -> None:
        px = m + int(self._pos * track_px)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(ACC)))
        painter.drawRoundedRect(m, ty, max(0, px - m), th, 2, 2)

    def _paint_markers(self, painter: QPainter, m: int, track_px: int, ty: int) -> None:
        if self._in > 0.001:
            ix = m + int(self._in * track_px)
            painter.setBrush(QBrush(QColor(ACC3)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygon([
                QPoint(ix, ty - 1),
                QPoint(ix - 5, ty - 8),
                QPoint(ix + 5, ty - 8),
            ]))
        if self._out < 0.999:
            ox = m + int(self._out * track_px)
            painter.setBrush(QBrush(QColor(ACC2)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygon([
                QPoint(ox, ty - 1),
                QPoint(ox - 5, ty - 8),
                QPoint(ox + 5, ty - 8),
            ]))

    def _paint_playhead(self, painter: QPainter, m: int, track_px: int,
                        ty: int, th: int) -> None:
        px = m + int(self._pos * track_px)
        painter.setBrush(QBrush(QColor(ACC)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPoint(px, ty + th // 2), self._HANDLE_R, self._HANDLE_R)

    # ── Input ──────────────────────────────────────────────────────
    def _pct(self, x: float) -> float:
        usable = max(1, self.width() - self._MARGIN * 2)
        return max(0.0, min(1.0, (x - self._MARGIN) / usable))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.seeked.emit(self._pct(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled():
            return
        x = int(event.position().x())
        pct = self._pct(x)
        self._hover_x = x
        self.update()
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.seeked.emit(pct)
        if self._duration:
            self.hoverTime.emit(
                pct * self._duration, x,
                int(event.globalPosition().y()),
            )

    def leaveEvent(self, _event) -> None:
        self._hover_x = -1
        self.update()
        self.hoverTime.emit(-1.0, -1, -1)
