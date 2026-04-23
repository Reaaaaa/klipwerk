"""The big video preview pane with interactive crop selection."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import QLabel, QSizePolicy

from ..core.models import CropRect
from ..ui.theme import ACC, BG, BORDER, MUTED


class PreviewWidget(QLabel):
    """Displays video frames and hosts the crop-drag interaction.

    The widget keeps an internal ``_pixmap_base`` (the raw decoded
    frame) and re-composites it on every paint — drawing the frame,
    then darkening everything outside the crop rect, then the crop
    border with a rule-of-thirds overlay.
    """

    cropChanged = pyqtSignal(dict)   # emits {x, y, w, h} in video pixels

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(400, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            f"background:{BG}; border:1px solid {BORDER}; "
            f"color:{MUTED}; font-size:13px;"
        )
        self.setText("Drop a video here\nor click  Open File")

        # Anti-flicker during window resize: we fully repaint in
        # paintEvent, so Qt doesn't need to pre-clear the background
        # itself. WA_StyledBackground is still needed so the setStyleSheet
        # border actually renders.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Crop state
        self.crop_mode: bool = False
        self.crop_rect: QRect | None = None   # widget coordinates
        self._drag_start: QPoint | None = None
        self._scale: float = 1.0
        self._offset: QPoint = QPoint(0, 0)      # top-left of image in widget
        self._vid_w: int = 0
        self._vid_h: int = 0
        self._pixmap_base: QPixmap | None = None

    # ── Frame update ────────────────────────────────────────────────
    def set_frame(self, pixmap: QPixmap, vid_w: int, vid_h: int) -> None:
        self._pixmap_base = pixmap
        self._vid_w = vid_w
        self._vid_h = vid_h
        self._recalc_scale()
        self._repaint_frame()

    def reset(self) -> None:
        """Clear the preview and return to the drop-a-video placeholder."""
        self._pixmap_base = None
        self._vid_w = self._vid_h = 0
        self.crop_rect = None
        self.clear()
        self.setText("Drop a video here\nor click  Open File")

    def _recalc_scale(self) -> None:
        if not self._vid_w or not self._vid_h:
            return
        ww, wh = self.width(), self.height()
        if ww <= 0 or wh <= 0:
            return
        self._scale = min(ww / self._vid_w, wh / self._vid_h)
        dw = int(self._vid_w * self._scale)
        dh = int(self._vid_h * self._scale)
        self._offset = QPoint((ww - dw) // 2, (wh - dh) // 2)

    def _repaint_frame(self) -> None:
        if self._pixmap_base is None:
            return
        dw = int(self._vid_w * self._scale)
        dh = int(self._vid_h * self._scale)

        scaled = self._pixmap_base.scaled(
            dw, dh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        canvas = QPixmap(self.width(), self.height())
        canvas.fill(QColor(BG))
        painter = QPainter(canvas)
        try:
            painter.drawPixmap(self._offset, scaled)

            if self.crop_rect and self.crop_rect.width() > 2:
                self._paint_crop_overlay(painter, dw, dh)
        finally:
            painter.end()

        self.setPixmap(canvas)

    def _paint_crop_overlay(self, painter: QPainter, dw: int, dh: int) -> None:
        cr = self.crop_rect
        assert cr is not None
        img_rect = QRect(self._offset, QSize(dw, dh))

        # Darken everything outside the crop — four rects around it.
        painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRect(
            img_rect.left(), img_rect.top(),
            img_rect.width(), cr.top() - img_rect.top(),
        ))
        painter.drawRect(QRect(
            img_rect.left(), cr.bottom(),
            img_rect.width(), img_rect.bottom() - cr.bottom(),
        ))
        painter.drawRect(QRect(
            img_rect.left(), cr.top(),
            cr.left() - img_rect.left(), cr.height(),
        ))
        painter.drawRect(QRect(
            cr.right(), cr.top(),
            img_rect.right() - cr.right(), cr.height(),
        ))

        # Crop border
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(ACC), 1.5))
        painter.drawRect(cr)

        # Rule-of-thirds guides
        painter.setPen(QPen(QColor(ACC).darker(150), 0.5, Qt.PenStyle.DashLine))
        for i in (1, 2):
            painter.drawLine(
                cr.left() + cr.width() * i // 3, cr.top(),
                cr.left() + cr.width() * i // 3, cr.bottom(),
            )
            painter.drawLine(
                cr.left(), cr.top() + cr.height() * i // 3,
                cr.right(), cr.top() + cr.height() * i // 3,
            )

    # ── Crop interaction ────────────────────────────────────────────
    def set_crop_mode(self, enabled: bool) -> None:
        self.crop_mode = enabled
        self.setCursor(QCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        ))

    def clear_crop(self) -> None:
        self.crop_rect = None
        self._repaint_frame()

    def set_crop_from_video(self, x: int, y: int, w: int, h: int) -> None:
        """Set the crop rect from video-pixel coordinates."""
        s = self._scale
        ox, oy = self._offset.x(), self._offset.y()
        self.crop_rect = QRect(
            int(ox + x * s), int(oy + y * s),
            int(w * s), int(h * s),
        )
        self._repaint_frame()

    def _widget_to_video(self, point: QPoint) -> tuple[int, int]:
        s = self._scale
        if s == 0:
            return (0, 0)
        ox, oy = self._offset.x(), self._offset.y()
        return (int((point.x() - ox) / s), int((point.y() - oy) / s))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.crop_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self.crop_rect = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (self.crop_mode and self._drag_start):
            return

        cur = event.position().toPoint()
        x = min(self._drag_start.x(), cur.x())
        y = min(self._drag_start.y(), cur.y())
        w = abs(cur.x() - self._drag_start.x())
        h = abs(cur.y() - self._drag_start.y())

        # Clamp to the scaled image rect
        img_rect = QRect(
            self._offset,
            QSize(int(self._vid_w * self._scale), int(self._vid_h * self._scale)),
        )
        x = max(img_rect.left(), min(x, img_rect.right()))
        y = max(img_rect.top(),  min(y, img_rect.bottom()))
        w = min(w, img_rect.right()  - x)
        h = min(h, img_rect.bottom() - y)

        self.crop_rect = QRect(x, y, w, h)
        self._repaint_frame()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not (self.crop_mode and self._drag_start and self.crop_rect):
            return

        self._drag_start = None
        cr = self.crop_rect
        if cr.width() > 4 and cr.height() > 4:
            vx, vy = self._widget_to_video(cr.topLeft())
            vx2, vy2 = self._widget_to_video(cr.bottomRight())
            # ffmpeg encoders need even dimensions
            vw = (vx2 - vx) & ~1
            vh = (vy2 - vy) & ~1
            vw = max(2, min(vw, self._vid_w - vx))
            vh = max(2, min(vh, self._vid_h - vy))
            crop: CropRect = {"x": vx, "y": vy, "w": vw, "h": vh}
            self.cropChanged.emit(crop)
        self.set_crop_mode(False)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._recalc_scale()
        self._repaint_frame()
