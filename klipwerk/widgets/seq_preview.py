"""Standalone floating window for previewing all clips in sequence.

Completely independent from the main player — owns its own
``cv2.VideoCapture`` and ``QTimer`` so it never conflicts with the
editor's playback state. Uses the same frameless custom title bar as
the main window.
"""
from __future__ import annotations

import cv2
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Clip
from ..ui.icons import SVG_CLOSE, SVG_MAXIMIZE, SVG_MINIMIZE, SVG_RESTORE, make_icon
from ..ui.theme import (
    ACC,
    ACC2,
    BG,
    BORDER2,
    MUTED,
    MUTED2,
    S1,
    S2,
    S3,
    TEXT,
)
from .helpers import btn, label


class SequencePreviewWindow(QWidget):
    """Floating frameless preview window that plays all clips back-to-back.

    Opens with auto-play on the first clip. The user can step between
    clips, pause/resume, or close the window at any time. Closing
    releases the ``VideoCapture`` handle cleanly.

    Keyboard shortcuts (while window is focused):
      Space       play / pause
      ← / ,       previous clip
      → / .       next clip
      Esc         close
    """

    _RESIZE_MARGIN = 6

    def __init__(
        self,
        video_path: str,
        clips: list[Clip],
        fps: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinimizeButtonHint,
        )
        self.resize(840, 540)
        self.setMinimumSize(480, 340)

        # drag / resize state
        self._drag_pos: QPoint | None = None
        self._resizing = False
        self._resize_dir: str | None = None
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        self._video_path = video_path
        self._clips      = list(clips)
        self._fps        = fps if fps > 0 else 30.0
        self._interval   = max(15, int(1000 / self._fps))
        self._idx        = 0
        self._playing    = False
        self._last_px: QPixmap | None = None

        self._cap = cv2.VideoCapture(video_path)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._build_ui()
        self.installEventFilter(self)
        self._load_clip(0)
        self._play()

    # ── UI ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"QWidget {{ background:{BG}; color:{TEXT};"
            f" font-family:'Consolas','Courier New',monospace; }}"
            f"QLabel  {{ background:transparent; }}"
            f"QPushButton {{ background:{S3}; border:2px solid {BORDER2};"
            f" color:{TEXT}; padding:4px 12px; border-radius:4px;"
            f" font-size:12px; outline:none; }}"
            f"QPushButton:hover  {{ border-color:{ACC}; color:{ACC}; }}"
            f"QPushButton:pressed {{ background:{S2}; }}"
            f"QPushButton:disabled {{ color:{MUTED}; border-color:{BORDER2}; }}"
            f"QPushButton#danger:hover {{ border-color:{ACC2}; color:{ACC2}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title bar ────────────────────────────────────────────────
        self._titlebar = self._build_titlebar()
        root.addWidget(self._titlebar)

        # ── Video display ────────────────────────────────────────────
        self._display = QLabel()
        self._display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self._display.setStyleSheet(f"background:{BG};")
        root.addWidget(self._display, 1)

        # ── Controls strip ───────────────────────────────────────────
        bar = QWidget()
        bar.setStyleSheet(f"background:{S1}; border-top:1px solid {BORDER2};")
        bar.setFixedHeight(76)
        bar_lay = QVBoxLayout(bar)
        bar_lay.setContentsMargins(14, 8, 14, 10)
        bar_lay.setSpacing(6)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{MUTED2}; font-size:11px; background:transparent;"
        )
        bar_lay.addWidget(self._status_lbl)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        self._btn_prev = btn("◀  Prev");  self._btn_prev.setFixedHeight(32)
        self._btn_play = btn("▶  Play");  self._btn_play.setFixedHeight(32)
        self._btn_next = btn("Next  ▶");  self._btn_next.setFixedHeight(32)
        self._btn_stop = btn("■  Stop", danger=True); self._btn_stop.setFixedHeight(32)

        self._btn_prev.clicked.connect(self._prev_clip)
        self._btn_play.clicked.connect(self._toggle_play)
        self._btn_next.clicked.connect(self._next_clip)
        self._btn_stop.clicked.connect(self.close)

        btns.addWidget(self._btn_prev)
        btns.addWidget(self._btn_play)
        btns.addWidget(self._btn_next)
        btns.addStretch()
        btns.addWidget(self._btn_stop)
        bar_lay.addLayout(btns)
        root.addWidget(bar)

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{S1}; border-bottom:1px solid {BORDER2};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        logo = QLabel(f"KLIP<span style='color:{TEXT}'>WERK</span>")
        logo.setStyleSheet(
            f"color:{ACC}; font-family:'Consolas'; font-weight:900;"
            f" font-size:15px; background:transparent; letter-spacing:-1px;"
        )
        logo.setTextFormat(Qt.TextFormat.RichText)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{BORDER2};")
        sep.setFixedSize(1, 20)

        title = label("Preview Sequence", color=MUTED2, size=11)

        btn_min   = self._make_win_btn(SVG_MINIMIZE, ACC,  "Minimize", "#000")
        btn_max   = self._make_win_btn(SVG_MAXIMIZE, S3,   "Maximize", TEXT)
        btn_close = self._make_win_btn(SVG_CLOSE,    ACC2, "Close",    "#fff")
        btn_min.clicked.connect(self.showMinimized)
        btn_max.clicked.connect(self._toggle_maximize)
        btn_close.clicked.connect(self.close)
        self._btn_max = btn_max

        lay.addWidget(logo)
        lay.addWidget(sep)
        lay.addWidget(title)
        lay.addStretch()
        lay.addWidget(btn_min)
        lay.addWidget(btn_max)
        lay.addWidget(btn_close)
        return bar

    def _make_win_btn(
        self, svg_tpl: str, hover_bg: str, tip: str, hover_icon: str,
    ) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(30, 30)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setIcon(make_icon(svg_tpl, MUTED2, 13))
        b.setIconSize(QSize(13, 13))
        b.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f" border-radius:5px; padding:0; }}"
            f"QPushButton:hover {{ background:{hover_bg}; }}"
        )
        def on_enter(_e, _s=svg_tpl, _c=hover_icon): b.setIcon(make_icon(_s, _c, 13))
        def on_leave(_e, _s=svg_tpl):                b.setIcon(make_icon(_s, MUTED2, 13))
        b.enterEvent = on_enter  # type: ignore[assignment]
        b.leaveEvent = on_leave  # type: ignore[assignment]
        return b

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._btn_max.setIcon(make_icon(SVG_MAXIMIZE, MUTED2, 13))
        else:
            self.showMaximized()
            self._btn_max.setIcon(make_icon(SVG_RESTORE, MUTED2, 13))

    # ── Playback ─────────────────────────────────────────────────────

    def _load_clip(self, idx: int) -> None:
        if not self._cap or not (0 <= idx < len(self._clips)):
            return
        self._idx = idx
        c = self._clips[idx]
        self._cap.set(cv2.CAP_PROP_POS_MSEC, c.start * 1000)
        self._update_status()
        ret, frame = self._cap.read()
        if ret:
            self._show_frame(frame)

    def _tick(self) -> None:
        if not self._cap:
            return
        ret, frame = self._cap.read()
        if not ret:
            self._next_clip()
            return
        current_t = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        self._show_frame(frame)
        if current_t >= self._clips[self._idx].end:
            self._next_clip()

    def _play(self) -> None:
        self._playing = True
        self._btn_play.setText("⏸  Pause")
        self._timer.start(self._interval)

    def _pause(self) -> None:
        self._playing = False
        self._btn_play.setText("▶  Play")
        self._timer.stop()

    def _toggle_play(self) -> None:
        self._pause() if self._playing else self._play()

    def _prev_clip(self) -> None:
        if self._idx > 0:
            was = self._playing
            self._pause()
            self._load_clip(self._idx - 1)
            if was:
                self._play()

    def _next_clip(self) -> None:
        if self._idx + 1 < len(self._clips):
            was = self._playing
            self._pause()
            self._load_clip(self._idx + 1)
            if was:
                self._play()
        else:
            self._pause()
            self._status_lbl.setText("✓  Sequence complete")

    # ── Rendering ────────────────────────────────────────────────────

    def _show_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._last_px = QPixmap.fromImage(qimg)
        self._redisplay()

    def _redisplay(self) -> None:
        if self._last_px is None:
            return
        scaled = self._last_px.scaled(
            self._display.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._display.setPixmap(scaled)

    def _update_status(self) -> None:
        c = self._clips[self._idx]
        n = len(self._clips)
        dur = c.end - c.start
        self._status_lbl.setText(
            f"Clip {self._idx + 1} / {n}  ·  {c.name}  ·  {dur:.1f}s"
        )

    # ── Window chrome (drag + resize) ────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._titlebar.geometry().contains(pos) and not self.isMaximized():
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        else:
            self._drag_pos = None
        self._resize_dir = self._get_resize_dir(pos)
        if self._resize_dir:
            self._resizing = True
            self._resize_start_geo  = self.geometry()
            self._resize_start_pos  = event.globalPosition().toPoint()
            QApplication.restoreOverrideCursor()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        elif self._resizing and (event.buttons() & Qt.MouseButton.LeftButton):
            self._do_resize(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_pos    = None
        self._resizing    = False
        self._resize_dir  = None

    def mouseDoubleClickEvent(self, event) -> None:
        if self._titlebar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseMove and not self._resizing:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            d = self._get_resize_dir(pos)
            cursors = {
                "left": Qt.CursorShape.SizeHorCursor,
                "right": Qt.CursorShape.SizeHorCursor,
                "top": Qt.CursorShape.SizeVerCursor,
                "bottom": Qt.CursorShape.SizeVerCursor,
                "top-left": Qt.CursorShape.SizeFDiagCursor,
                "bottom-right": Qt.CursorShape.SizeFDiagCursor,
                "top-right": Qt.CursorShape.SizeBDiagCursor,
                "bottom-left": Qt.CursorShape.SizeBDiagCursor,
            }
            if d:
                QApplication.setOverrideCursor(cursors.get(d, Qt.CursorShape.ArrowCursor))
            else:
                QApplication.restoreOverrideCursor()
        return super().eventFilter(obj, event)

    def _get_resize_dir(self, pos: QPoint) -> str | None:
        if self.isMaximized():
            return None
        m = self._RESIZE_MARGIN
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        left, right = x < m, x > w - m
        top, bottom = y < m, y > h - m
        if top and left:     return "top-left"
        if top and right:    return "top-right"
        if bottom and left:  return "bottom-left"
        if bottom and right: return "bottom-right"
        if left:   return "left"
        if right:  return "right"
        if top:    return "top"
        if bottom: return "bottom"
        return None

    def _do_resize(self, global_pos: QPoint) -> None:
        if self._resize_start_geo is None or self._resize_start_pos is None:
            return
        delta = global_pos - self._resize_start_pos
        geo = QRect(self._resize_start_geo)
        d = self._resize_dir or ""
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if "left"   in d: geo.setLeft(min(geo.left()   + delta.x(), geo.right()  - min_w))
        if "right"  in d: geo.setRight(max(geo.right() + delta.x(), geo.left()   + min_w))
        if "top"    in d: geo.setTop(min(geo.top()     + delta.y(), geo.bottom() - min_h))
        if "bottom" in d: geo.setBottom(max(geo.bottom() + delta.y(), geo.top()  + min_h))
        if geo.topLeft() == self._resize_start_geo.topLeft():
            self.resize(geo.size())
        else:
            self.setGeometry(geo)

    # ── Qt overrides ─────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redisplay()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        k = event.key()
        if k == Qt.Key.Key_Space:
            self._toggle_play()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self._prev_clip()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self._next_clip()
        elif k == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._pause()
        if self._cap:
            self._cap.release()
            self._cap = None
        QApplication.restoreOverrideCursor()
        super().closeEvent(event)
