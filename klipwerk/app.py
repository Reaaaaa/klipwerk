"""The Klipwerk main window.

Orchestration-only: most of the heavy lifting lives in submodules
(``workers``, ``widgets``, ``sidebar``, ``history``, ``core``).

Organized into four loose sections separated by the big banner comments:

1. Setup: ``__init__``, UI build, shortcuts, tooltips, K/C mode
2. Video loading, playback, seeking
3. Crop, Mark In/Out, clip CRUD, undo/redo
4. Export
"""
from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

import cv2
from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QCursor,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .core.export_builder import crop_vf_args, plan_sequence_export
from .core.ffmpeg_runner import ffmpeg_bin
from .core.formats import FORMATS, codec_args, pick_default_for
from .core.models import Clip, CropRect
from .core.probe import probe_video
from .history import History
from .settings import Settings
from .sidebar import SidebarRefs, build_sidebar
from .ui.icons import (
    SVG_CLOSE,
    SVG_MAXIMIZE,
    SVG_MINIMIZE,
    SVG_RESTORE,
    make_icon,
)
from .ui.theme import (
    ACC,
    ACC2,
    ACC3,
    BG,
    BORDER,
    BORDER2,
    MUTED,
    MUTED2,
    S1,
    S2,
    S3,
    STYLE,
    TEXT,
)
from .widgets.clip_item import ClipItem, TimelineClip
from .widgets.helpers import btn, label
from .widgets.preview import PreviewWidget
from .widgets.scrubber import ScrubberWidget
from .workers.ffmpeg_worker import FFmpegWorker, SequenceFFmpegWorker
from .workers.waveform import WaveformWorker

log = logging.getLogger(__name__)


# Filename-safe character filter (Windows + POSIX)
_FNAME_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitize(s: str) -> str:
    return _FNAME_RE.sub("_", s)


# =============================================================================
# Section 1 — Setup, UI build, shortcuts
# =============================================================================
class Klipwerk(QMainWindow):
    """Top-level window. Owns all state and wires subwidgets together."""

    # Resize handling for the frameless window
    _RESIZE_MARGIN = 6

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Klipwerk")
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._drag_pos: QPoint | None = None
        self._resizing = False
        self._resize_dir: str | None = None
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        # ── State ──────────────────────────────────────────────────
        self.video_path: str | None = None
        self.cap: cv2.VideoCapture | None = None
        self.duration: float = 0.0
        self.vid_w: int = 0
        self.vid_h: int = 0
        self.fps: float = 30.0
        self.current_t: float = 0.0
        self.playing: bool = False
        self.crop_rect: CropRect | None = None
        self.mark_in: float = 0.0
        self.mark_out: float = 0.0

        self.clips: list[Clip] = []
        self.history = History(self.clips)
        self.active_clip: int = -1

        # Widget index → we diff the clip list against these to avoid
        # destroying/rebuilding every row on every edit.
        self._clip_items: dict[str, ClipItem] = {}
        self._timeline_items: dict[str, TimelineClip] = {}

        self._worker: FFmpegWorker | None = None
        self._waveform_worker: WaveformWorker | None = None

        self._tooltips_enabled = True
        self._seq_idx = -1
        self._seq_active = False
        self._use_k_mode = True   # K=Klip by default; C=Clip toggle
        self._hover_show_frames = False

        # Persistence — loaded here, applied after the UI is built.
        self.settings = Settings()

        # ── Build UI ───────────────────────────────────────────────
        self._build_ui()
        self._setup_shortcuts()
        self._set_tooltips(True)
        self._init_hover_label()

        # Playback timer — period adjusts to video fps on load.
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        # Cursor / resize handling for the frameless window needs global
        # mouse events, otherwise child widgets swallow them first.
        self.centralWidget().setMouseTracking(True)
        self.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

        # Restore user preferences (geometry, export defaults, K/C mode).
        # Must happen after _build_ui so the widgets exist.
        self._apply_settings()

    # ── Top-level build ────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_main(), 1)
        root.addWidget(self._build_timeline())

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(52)
        w.setObjectName("titlebar")
        w.setStyleSheet(f"background:{S1}; border-bottom:1px solid {BORDER2};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(12)

        logo = QLabel(f"KLIP<span style='color:{TEXT}'>WERK</span>")
        logo.setStyleSheet(
            f"color:{ACC}; font-family:'Consolas'; font-weight:900; "
            f"font-size:17px; background:transparent; letter-spacing:-1px;"
        )
        logo.setTextFormat(Qt.TextFormat.RichText)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{BORDER2};")
        sep.setFixedSize(1, 24)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color:{ACC}; font-size:13px; background:transparent;")
        self.status_label = label("ready", color=MUTED2, size=12)

        self.fname_label = label("", color=MUTED2, size=12)
        self.fname_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        btn_min   = self._make_win_btn(SVG_MINIMIZE, ACC,  "Minimize", "#000")
        btn_max   = self._make_win_btn(SVG_MAXIMIZE, S3,   "Maximize", TEXT)
        btn_close = self._make_win_btn(SVG_CLOSE,    ACC2, "Close",    "#fff")
        btn_min.clicked.connect(self.showMinimized)
        btn_max.clicked.connect(self._toggle_maximize)
        btn_close.clicked.connect(self.close)
        self._btn_max = btn_max

        lay.addWidget(logo)
        lay.addWidget(sep)
        lay.addWidget(self.status_dot)
        lay.addWidget(self.status_label)
        lay.addStretch()
        lay.addWidget(self.fname_label)
        lay.addSpacing(16)
        lay.addWidget(btn_min)
        lay.addWidget(btn_max)
        lay.addWidget(btn_close)

        self._titlebar = w
        return w

    def _make_win_btn(
        self, svg_tpl: str, hover_bg: str, tip: str, hover_icon: str,
    ) -> QPushButton:
        """Window chrome button (min/max/close). Swaps icon color on hover."""
        b = QPushButton()
        b.setFixedSize(32, 32)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setIcon(make_icon(svg_tpl, MUTED2, 14))
        b.setIconSize(QSize(14, 14))
        b.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f" border-radius:6px; padding:0; }}"
            f"QPushButton:hover {{ background:{hover_bg}; }}"
        )

        def on_enter(_event, _svg=svg_tpl, _color=hover_icon):
            b.setIcon(make_icon(_svg, _color, 14))

        def on_leave(_event, _svg=svg_tpl):
            b.setIcon(make_icon(_svg, MUTED2, 14))

        b.enterEvent = on_enter   # type: ignore[assignment]
        b.leaveEvent = on_leave   # type: ignore[assignment]
        return b

    def _build_main(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Left side — preview + toolbar + playback
        left = QWidget()
        left.setStyleSheet(f"background:{BG};")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)   # breathing room so the toolbar's
                                 # bottom border doesn't sit flush on
                                 # the preview frame
        left_lay.addWidget(self._build_toolbar())
        self.preview = PreviewWidget()
        self.preview.cropChanged.connect(self._on_crop_drawn)
        left_lay.addWidget(self.preview, 1)
        left_lay.addWidget(self._build_playback())

        # Right side — sidebar
        self.sidebar: SidebarRefs = build_sidebar(
            on_crop_changed=self._on_crop_fields_changed,
            on_mark_in_changed=lambda v: setattr(self, "mark_in", v),
            on_mark_out_changed=lambda v: setattr(self, "mark_out", v),
            on_fmt_changed=self._on_fmt_changed,
            on_prefix_changed=lambda _: self._update_fname_preview(),
            on_suffix_crop_changed=lambda _: self._update_fname_preview(),
            on_suffix_clip_changed=lambda _: self._update_fname_preview(),
            on_suffix_seq_changed=lambda _: self._update_fname_preview(),
            set_crop_preset=self._set_crop_preset,
            on_add_klip=self._add_clip,
            on_export_crop=lambda: self._export("crop"),
            on_export_clip=lambda: self._export("clip"),
            on_export_seq=lambda: self._export("sequence"),
        )
        self.sidebar.widget.setMinimumWidth(260)
        self.sidebar.info_header.mousePressEvent = (
            lambda _e: self._toggle_info_panel()
        )

        splitter.addWidget(left)
        splitter.addWidget(self.sidebar.widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, 310])

        self._update_codec_note(0)
        return splitter

    def _build_toolbar(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(52)
        w.setStyleSheet(f"background:{S1}; border-bottom:1px solid {BORDER2};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        self.btn_crop = btn("✂  Crop", compact=True); self.btn_crop.setCheckable(True)
        self.btn_crop.setFixedHeight(30)
        self.btn_crop.toggled.connect(lambda c: self.preview.set_crop_mode(c))
        self.btn_crop.setDisabled(True)

        self.btn_crop_clr = btn("✕  Clear Crop", danger=True, compact=True)
        self.btn_crop_clr.setFixedHeight(30)
        self.btn_crop_clr.clicked.connect(self._clear_crop)
        self.btn_crop_clr.setDisabled(True)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{BORDER2};"); sep.setFixedWidth(1)

        self.btn_in  = btn("[  In",  compact=True); self.btn_in.setFixedHeight(30)
        self.btn_out = btn("Out  ]", compact=True); self.btn_out.setFixedHeight(30)
        self.btn_in.clicked.connect(lambda: self._set_mark("in"))
        self.btn_out.clicked.connect(lambda: self._set_mark("out"))
        self.btn_in.setDisabled(True)
        self.btn_out.setDisabled(True)

        self.btn_add_clip = btn("+  Add Klip", compact=True)
        self.btn_add_clip.setFixedHeight(30)
        self.btn_add_clip.clicked.connect(self._add_clip)
        self.btn_add_clip.setDisabled(True)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color:{BORDER2};"); sep2.setFixedWidth(1)

        btn_open = btn("⊕  Open File", compact=True); btn_open.setFixedHeight(30)
        btn_open.clicked.connect(self._open_file_dialog)

        self.btn_close_vid = btn("⏏  Close Video", danger=True, compact=True)
        self.btn_close_vid.setFixedHeight(30)
        self.btn_close_vid.clicked.connect(self._close_video)
        self.btn_close_vid.setDisabled(True)

        self.btn_preview_seq = btn("▶  Preview Sequence", compact=True)
        self.btn_preview_seq.setFixedHeight(30)
        self.btn_preview_seq.clicked.connect(self._preview_sequence)
        self.btn_preview_seq.setDisabled(True)

        self.btn_tips = btn("? Tips", compact=True); self.btn_tips.setFixedHeight(30)
        self.btn_tips.setCheckable(True); self.btn_tips.setChecked(True)
        self.btn_tips.toggled.connect(self._toggle_tooltips)
        self.btn_tips.setStyleSheet(
            f"QPushButton {{ background:{S3}; border:1px solid {BORDER2};"
            f" color:{MUTED2}; font-size:11px; border-radius:5px;"
            f" padding:4px 10px; outline:none; }}"
            f"QPushButton:checked {{ background:{S2}; border-color:{ACC3}; color:{ACC3}; }}"
            f"QPushButton:hover {{ border-color:{ACC3}; color:{ACC3}; }}"
        )

        self.btn_klip_toggle = QPushButton("C/K")
        self.btn_klip_toggle.setFixedHeight(30)
        self.btn_klip_toggle.setCheckable(True)
        self.btn_klip_toggle.blockSignals(True)
        self.btn_klip_toggle.setChecked(True)
        self.btn_klip_toggle.blockSignals(False)
        self.btn_klip_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_klip_toggle.setToolTip("Toggle between 'Klip' (K) and 'Clip' (C)")
        self.btn_klip_toggle.setStyleSheet(
            f"QPushButton {{ background:{S3}; border:1px solid {BORDER2};"
            f" color:{MUTED2}; font-size:11px; font-weight:bold;"
            f" border-radius:5px; padding:4px 10px; outline:none; }}"
            f"QPushButton:checked {{ background:{S2}; border-color:{ACC}; color:{ACC}; }}"
            f"QPushButton:hover {{ border-color:{ACC}; color:{ACC}; }}"
        )
        self.btn_klip_toggle.toggled.connect(self._toggle_klip_mode)

        lay.addWidget(self.btn_crop)
        lay.addWidget(self.btn_crop_clr)
        lay.addWidget(sep)
        lay.addWidget(self.btn_in)
        lay.addWidget(self.btn_out)
        lay.addWidget(self.btn_add_clip)
        lay.addWidget(sep2)
        lay.addStretch()
        lay.addWidget(self.btn_preview_seq)
        lay.addWidget(self.btn_klip_toggle)
        lay.addWidget(self.btn_tips)
        lay.addWidget(self.btn_close_vid)
        lay.addWidget(btn_open)
        return w

    def _build_playback(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(128)
        w.setStyleSheet(f"background:{S1}; border-top:1px solid {BORDER2};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(6)

        self.scrubber = ScrubberWidget()
        self.scrubber.seeked.connect(self._seek)
        self.scrubber.hoverTime.connect(self._on_scrubber_hover)

        self.btn_prev = btn("◀◀"); self.btn_prev.setFixedSize(42, 36)
        self.btn_next = btn("▶▶"); self.btn_next.setFixedSize(42, 36)
        self.btn_play = QPushButton("▶"); self.btn_play.setFixedSize(52, 36)

        transport_style = (
            f"QPushButton {{ background:{S3}; border:1px solid {BORDER2};"
            f" color:{TEXT}; font-size:15px; font-weight:bold;"
            f" border-radius:5px; outline:none; }}"
            f"QPushButton:hover {{ border-color:{ACC}; color:{ACC}; background:{S3}; }}"
            f"QPushButton:pressed {{ background:{S2}; color:{TEXT}; }}"
            f"QPushButton:disabled {{ color:{MUTED}; border-color:{BORDER}; background:{S2}; }}"
        )
        play_style = (
            f"QPushButton {{ background:{ACC}; border:1px solid {ACC};"
            f" color:#000; font-size:15px; font-weight:bold;"
            f" border-radius:5px; outline:none; }}"
            f"QPushButton:hover {{ background:#d4ff45; border-color:#d4ff45; color:#000; }}"
            f"QPushButton:pressed {{ background:#b8e030; color:#000; }}"
            f"QPushButton:disabled {{ background:{S3}; color:{MUTED}; border-color:{BORDER}; }}"
        )
        self.btn_prev.setStyleSheet(transport_style)
        self.btn_next.setStyleSheet(transport_style)
        self.btn_play.setStyleSheet(play_style)

        for b in (self.btn_prev, self.btn_play, self.btn_next):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setDisabled(True)

        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_next.clicked.connect(lambda: self._step(1))

        self.timecode = label("--:--:-- / --:--:--", color=MUTED2, size=11)
        self.timecode.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        marker_row = QHBoxLayout()
        marker_row.setContentsMargins(0, 0, 0, 0)
        self.in_label  = label("In: --:--:--", color=ACC3,  size=10)
        self.out_label = label("Out: --:--:--", color=ACC2, size=10)
        marker_row.addWidget(self.in_label)
        marker_row.addSpacing(10)
        marker_row.addWidget(self.out_label)
        marker_row.addStretch()
        marker_row.addWidget(self.timecode)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addWidget(self.btn_prev)
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_next)
        ctrl.addStretch()

        lay.addWidget(self.scrubber)
        lay.addLayout(marker_row)
        lay.addLayout(ctrl)
        return w

    def _build_timeline(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(90)
        w.setStyleSheet(f"background:{S1}; border-top:1px solid {BORDER2};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(26)
        hdr.setStyleSheet(f"background:{S2}; border-bottom:1px solid {BORDER};")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 0, 14, 0)
        hdr_lay.addWidget(label("▶  TIMELINE", color=MUTED2, size=10))
        hdr_lay.addStretch()
        self.tl_info = label("drag Klips to reorder", color=MUTED, size=10)
        hdr_lay.addWidget(self.tl_info)

        self.tl_scroll = QScrollArea()
        self.tl_scroll.setWidgetResizable(False)
        self.tl_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tl_scroll.setStyleSheet(f"background:{BG}; border:none;")
        self.tl_container = QWidget()
        self.tl_container.setFixedHeight(60)
        self.tl_container.setStyleSheet(f"background:{BG};")
        self.tl_lay = QHBoxLayout(self.tl_container)
        self.tl_lay.setContentsMargins(10, 3, 10, 3)
        self.tl_lay.setSpacing(5)
        self.tl_lay.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.tl_scroll.setWidget(self.tl_container)

        lay.addWidget(hdr)
        lay.addWidget(self.tl_scroll)
        return w

    # ── Shortcuts + hover label + tooltips ─────────────────────────
    def _setup_shortcuts(self) -> None:
        def sc(keys: str, fn):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(fn)

        sc("Space",        self._toggle_play)
        sc("I",            lambda: self._set_mark("in"))
        sc("O",            lambda: self._set_mark("out"))
        sc("C",            self._add_clip)
        sc("Left",         lambda: self._step(-1))
        sc("Right",        lambda: self._step(1))
        sc("Shift+Left",   lambda: self._step(-10))
        sc("Shift+Right",  lambda: self._step(10))
        sc("Ctrl+Z",       self._undo)
        sc("Ctrl+Y",       self._redo)
        sc("Ctrl+Shift+Z", self._redo)
        sc("Delete",       self._delete_active_clip)

    def _init_hover_label(self) -> None:
        from PyQt6.QtCore import QEasingCurve, QPropertyAnimation
        from PyQt6.QtWidgets import QGraphicsOpacityEffect

        lbl = QLabel(self.centralWidget())
        lbl.setStyleSheet(
            f"QLabel {{ background:{S2}; color:{ACC}; border:1px solid {ACC};"
            f" border-radius:4px; padding:3px 9px; font-size:11px;"
            f" font-family:'Consolas','Courier New',monospace; font-weight:bold; }}"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lbl.hide()

        fx = QGraphicsOpacityEffect(lbl)
        fx.setOpacity(0.0)
        lbl.setGraphicsEffect(fx)

        anim = QPropertyAnimation(fx, b"opacity")
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hover_label = lbl
        self._hover_opacity = fx
        self._hover_anim = anim
        self._hover_above: bool | None = None

    def _toggle_tooltips(self, checked: bool) -> None:
        self._tooltips_enabled = checked
        self._set_tooltips(checked)
        self.btn_tips.setText("? Tips  ON" if checked else "? Tips  OFF")

    def _set_tooltips(self, on: bool) -> None:
        """Toggle all the rich tooltips on the UI."""
        T = (lambda s: s) if on else (lambda _s: "")
        sb = self.sidebar

        # Toolbar
        self.btn_crop.setToolTip(T(
            "Enable crop mode\n"
            "Drag a region on the preview to define the crop area."
        ))
        self.btn_crop_clr.setToolTip(T("Clear crop selection"))
        self.btn_in.setToolTip(T("Set In marker  (I)\nStart point for the next klip."))
        self.btn_out.setToolTip(T("Set Out marker  (O)\nEnd point for the next klip."))
        self.btn_add_clip.setToolTip(T(
            "Create klip from the marked range (In → Out)  (C)"
        ))
        self.btn_close_vid.setToolTip(T("Close current video"))

        # Playback
        self.btn_prev.setToolTip(T("1 frame back  (←) · 10 frames: Shift+←"))
        self.btn_play.setToolTip(T("Play / Pause  (Space)"))
        self.btn_next.setToolTip(T("1 frame forward  (→) · 10 frames: Shift+→"))

        # Sidebar — crop
        crop_tips = {
            sb.crop_x: "Horizontal offset from the left edge (pixels)",
            sb.crop_y: "Vertical offset from the top edge (pixels)",
            sb.crop_w: "Crop width (pixels) — rounded down to an even number",
            sb.crop_h: "Crop height (pixels) — rounded down to an even number",
        }
        for widget, tip in crop_tips.items():
            widget.setToolTip(T(tip))
        for lbl_w, tip_w in [
            (sb.lbl_x, sb.crop_x), (sb.lbl_y, sb.crop_y),
            (sb.lbl_w, sb.crop_w), (sb.lbl_h, sb.crop_h),
        ]:
            lbl_w.setToolTip(tip_w.toolTip())

        sb.btn_ex_crop.setToolTip(T(
            "Export the video with the chosen crop.\n"
            "E.g. 16:9 → 9:16 for Instagram."
        ))

        # Sidebar — mark
        sb.mark_in_spin.setToolTip(T(
            "Klip start time in seconds.\nSeek to the desired frame and press [ In."
        ))
        sb.mark_out_spin.setToolTip(T(
            "Klip end time in seconds.\nSeek to the desired frame and press Out ]."
        ))
        sb.lbl_in.setToolTip(sb.mark_in_spin.toolTip())
        sb.lbl_out.setToolTip(sb.mark_out_spin.toolTip())

        # Sidebar — export
        sb.export_fmt.setToolTip(T(
            "Output format and video codec:\n"
            "• H.264 — universally compatible, largest files\n"
            "• H.265/HEVC — ~50% smaller than H.264\n"
            "• AV1 — smallest files, but very slow\n"
            "• VP9 — good balance for WebM/browser playback"
        ))
        sb.export_crf.setToolTip(T(
            "CRF = Constant Rate Factor\n"
            "Lower = better quality, larger file\n"
            "H.264 recommended: 18 (very good) – 23 (good) – 28 (ok)"
        ))
        sb.export_preset.setToolTip(T(
            "Encoding speed vs. compression:\n"
            "ultrafast / fast / medium / slow / veryslow"
        ))
        for lbl_ref, spin_ref in [
            (sb.lbl_fmt, sb.export_fmt),
            (sb.lbl_crf, sb.export_crf),
            (sb.lbl_preset, sb.export_preset),
        ]:
            lbl_ref.setToolTip(spin_ref.toolTip())

        sb.btn_ex_seq.setToolTip(T(
            "Export all timeline klips as one continuous video."
        ))
        sb.btn_ex_clip.setToolTip(T("Export only the currently selected klip."))
        sb.export_prefix.setToolTip(T(
            "Prefix added before the filename.\n"
            "e.g. 'project_' → project_myvideo_crop.mp4"
        ))
        sb.export_suffix_crop.setToolTip(T("Suffix for cropped-video exports."))
        sb.export_suffix_clip.setToolTip(T("Suffix for single-clip exports."))
        sb.export_suffix_seq.setToolTip(T("Suffix for sequence exports."))
        self.btn_preview_seq.setToolTip(T(
            "Play all klips back to back without exporting. Stops after the last klip."
        ))

        # Dotted-underline hint on labels when tips are on
        tip_style    = f"color:{MUTED2}; font-size:12px; text-decoration:underline dotted {MUTED};"
        no_tip_style = f"color:{MUTED2}; font-size:12px;"
        style = tip_style if on else no_tip_style
        for lbl_w in (sb.lbl_x, sb.lbl_y, sb.lbl_w, sb.lbl_h,
                      sb.lbl_in, sb.lbl_out,
                      sb.lbl_fmt, sb.lbl_crf, sb.lbl_preset):
            lbl_w.setStyleSheet(style)
            lbl_w.setCursor(QCursor(
                Qt.CursorShape.WhatsThisCursor if on else Qt.CursorShape.ArrowCursor,
            ))

        self.btn_tips.setToolTip(
            "Toggle tooltips · Tip: also hover over the labels (CRF, Format, X, In…), "
            "not only the input fields!"
        )

    # ── K / C mode ─────────────────────────────────────────────────
    def _k(self, word: str) -> str:
        """Swap Klip→Clip when C-mode is active."""
        if self._use_k_mode:
            return word
        return word.replace("Klip", "Clip").replace("klip", "clip")

    def _toggle_klip_mode(self, checked: bool) -> None:
        self._use_k_mode = checked
        self.btn_klip_toggle.setText("K" if checked else "C")
        self._refresh_klip_labels()

    def _refresh_klip_labels(self) -> None:
        k = self._k
        self.btn_add_clip.setText(f"+  {k('Add Klip')}")
        self.sidebar.btn_add_sidebar.setText(f"+  {k('Add as Klip')}")
        self.btn_preview_seq.setText(f"▶  Preview {k('Klips')}")
        self.sidebar.btn_ex_clip.setText(f"  Export Active {k('Klip')}")
        self.sidebar.btn_ex_seq.setText(f"  Export {k('Klips')} Sequence")
        self.sidebar.klips_section_label.setText(k("Klips"))
        if not self.clips:
            self.tl_info.setText(f"drag {k('Klips')} to reorder")
        self._render_clips()
        self._render_timeline()
        self._update_fname_preview()

    # ── Frameless window chrome ────────────────────────────────────
    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._btn_max.setIcon(make_icon(SVG_MAXIMIZE, MUTED2, 14))
        else:
            self.showMaximized()
            self._btn_max.setIcon(make_icon(SVG_RESTORE, MUTED2, 14))

    def _toggle_info_panel(self) -> None:
        visible = not self.sidebar.info_panel.isVisible()
        self.sidebar.info_panel.setVisible(visible)
        self.sidebar.info_toggle_lbl.setText("▾" if visible else "▸")

    # =============================================================
    # Section 2 — Video load, playback, seeking
    # =============================================================
    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.ts *.m4v);;"
            "All Files (*)",
        )
        if path:
            self._load_video(path)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self._load_video(path)
                break

    def _load_video(self, path: str) -> None:
        self._stop()
        if self.cap:
            self.cap.release()

        self.video_path = path
        info = probe_video(path)
        self.duration = info["duration"]
        self.vid_w = info["width"]
        self.vid_h = info["height"]
        self.mark_in = 0.0
        self.mark_out = self.duration
        self.current_t = 0.0

        self.cap = cv2.VideoCapture(path)
        self.fps = info.get("fps") or self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._timer.setInterval(max(16, int(1000 / self.fps)))

        name = Path(path).name
        self.fname_label.setText(name)
        self.setWindowTitle(f"Klipwerk — {name}")
        self.sidebar.info_label.setText(
            f"{name}   {self.vid_w}×{self.vid_h}  ·  {self.duration:.1f}s  ·  {self.fps:.2f}fps"
        )
        self._set_status("ready", ACC)

        self._populate_info_panel(info, name)
        self._autofill_crop_defaults()
        self._autofill_marks()
        self._autofill_export_format(info.get("v_codec", ""))

        self.scrubber.setEnabled(True)
        for b in (self.btn_crop, self.btn_in, self.btn_out, self.btn_add_clip,
                  self.btn_prev, self.btn_play, self.btn_next, self.btn_close_vid,
                  self.btn_preview_seq):
            b.setEnabled(True)
        self.btn_preview_seq.setEnabled(len(self.clips) >= 1)

        self._seek_to(0)
        self._update_fname_preview()
        self._start_waveform_extraction(path)
        self.scrubber.set_video(path, self.duration)

    def _populate_info_panel(self, info: dict, name: str) -> None:
        def fmt_time(s: float) -> str:
            h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:05.2f}"

        channel_names = {1: "Mono", 2: "Stereo", 4: "4ch", 6: "5.1", 8: "7.1"}
        ch = channel_names.get(info.get("a_channels", 0), f"{info.get('a_channels', 0)}ch")
        sr = info.get("a_samplerate", 0)
        audio = (f"{info.get('a_codec', '—')}  {ch}  {sr//1000}kHz"
                 if sr else info.get("a_codec", "—"))

        fps_display = f"{self.fps:.3f}".rstrip("0").rstrip(".") + " fps"
        fps_raw = info.get("fps_raw", "")
        if isinstance(fps_raw, str) and fps_raw.count("/") == 1:
            fps_display += f"  ({fps_raw})"

        rows = {
            "File":         name,
            "Container":    info.get("container", "—"),
            "Size":         info.get("size", "—"),
            "Bitrate":      info.get("bitrate", "—"),
            "Duration":     fmt_time(self.duration),
            "Resolution":   f"{self.vid_w} × {self.vid_h}",
            "Aspect":       info.get("dar", "—"),
            "FPS":          fps_display,
            "Video Codec":  f"{info.get('v_codec','—')}  {info.get('v_profile','')}".strip(),
            "Pixel Format": info.get("pix_fmt", "—"),
            "Color Space":  info.get("color", "—"),
            "Audio Codec":  info.get("a_codec", "—"),
            "Audio":        audio,
        }
        for key, val in rows.items():
            if key in self.sidebar.info_rows:
                self.sidebar.info_rows[key].setText(val or "—")

    def _autofill_crop_defaults(self) -> None:
        sb = self.sidebar
        for sp in (sb.crop_x, sb.crop_y):
            sp.blockSignals(True); sp.setValue(0); sp.blockSignals(False)

        sb.crop_w.blockSignals(True)
        sb.crop_w.setMaximum(self.vid_w)
        sb.crop_w.setValue(self.vid_w - (self.vid_w % 2))
        sb.crop_w.blockSignals(False)

        sb.crop_h.blockSignals(True)
        sb.crop_h.setMaximum(self.vid_h)
        sb.crop_h.setValue(self.vid_h - (self.vid_h % 2))
        sb.crop_h.blockSignals(False)

        sb.crop_x.setMaximum(self.vid_w)
        sb.crop_y.setMaximum(self.vid_h)

    def _autofill_marks(self) -> None:
        sb = self.sidebar
        sb.mark_in_spin.setMaximum(self.duration)
        sb.mark_out_spin.setMaximum(self.duration)
        sb.mark_in_spin.blockSignals(True)
        sb.mark_in_spin.setValue(0.0)
        sb.mark_in_spin.blockSignals(False)
        sb.mark_out_spin.blockSignals(True)
        sb.mark_out_spin.setValue(round(self.duration, 2))
        sb.mark_out_spin.blockSignals(False)
        self.scrubber.set_markers(0.0, 1.0)

    def _autofill_export_format(self, v_codec: str) -> None:
        idx = pick_default_for(v_codec)
        self.sidebar.export_fmt.setCurrentIndex(idx)

    def _start_waveform_extraction(self, path: str) -> None:
        self._set_status("extracting waveform…", "#f90")
        if self._waveform_worker and self._waveform_worker.isRunning():
            self._waveform_worker.cancel()
            self._waveform_worker.wait(500)

        ww = WaveformWorker(path, self.scrubber.width() or 800)
        self._waveform_worker = ww

        def on_waveform(peaks):
            self.scrubber.set_waveform(peaks)
            self._set_status("ready", ACC)

        ww.done.connect(on_waveform)
        ww.start()

    def _close_video(self) -> None:
        self._stop()
        if self.cap:
            self.cap.release()
            self.cap = None

        self.video_path = None
        self.duration = 0.0
        self.vid_w = self.vid_h = 0
        self.current_t = 0.0
        self.crop_rect = None

        self.preview.reset()

        self.fname_label.setText("")
        self.setWindowTitle("Klipwerk")
        self.sidebar.info_label.setText("No video loaded")
        for v in self.sidebar.info_rows.values():
            v.setText("—")
        if self.sidebar.info_panel.isVisible():
            self.sidebar.info_panel.hide()
            self.sidebar.info_toggle_lbl.setText("▸")
        self._set_status("ready", ACC)
        self._clear_crop()

        self.clips.clear()
        self.history = History(self.clips)
        self.active_clip = -1
        self._render_clips()
        self._render_timeline()

        for b in (self.btn_crop, self.btn_in, self.btn_out, self.btn_add_clip,
                  self.btn_prev, self.btn_play, self.btn_next,
                  self.btn_close_vid, self.btn_preview_seq):
            b.setEnabled(False)
        self.scrubber.clear_video()
        self.timecode.setText("--:--:-- / --:--:--")
        self.in_label.setText("In: --:--:--")
        self.out_label.setText("Out: --:--:--")
        self.sidebar.mark_in_spin.setValue(0)
        self.sidebar.mark_out_spin.setValue(0)

    # ── Playback ────────────────────────────────────────────────────
    def _tick(self) -> None:
        if not self.cap:
            return
        ret, frame = self.cap.read()
        if not ret:
            self._stop()
            return
        self.current_t = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        self._show_frame(frame)
        self._update_scrubber()

        # Sequence preview: jump to next clip when current out-point reached
        if self._seq_active and self._seq_idx >= 0 and self._seq_idx < len(self.clips):
            c = self.clips[self._seq_idx]
            if self.current_t >= c.end:
                self._jump_to_seq_clip(self._seq_idx + 1)

    def _toggle_play(self) -> None:
        if self.playing:
            self._stop()
        else:
            self._play()

    def _play(self) -> None:
        if not self.cap:
            return
        self.playing = True
        self.btn_play.setText("⏸")
        self._timer.start()

    def _stop(self, *, cancel_seq: bool = True) -> None:
        self.playing = False
        self._timer.stop()
        self.btn_play.setText("▶")
        if cancel_seq:
            self._seq_active = False
            self._seq_idx = -1

    def _step(self, direction: int) -> None:
        if not self.cap:
            return
        self._stop()
        t = max(0.0, min(self.duration, self.current_t + direction / self.fps))
        self._seek_to(t)

    def _seek(self, pct: float) -> None:
        if not self.cap:
            return
        self._seek_to(pct * self.duration)

    def _seek_to(self, t: float) -> None:
        if not self.cap:
            return
        self.current_t = max(0.0, min(self.duration, t))
        self.cap.set(cv2.CAP_PROP_POS_MSEC, self.current_t * 1000)
        ret, frame = self.cap.read()
        if ret:
            self._show_frame(frame)
        self._update_scrubber()

    def _show_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        # .copy() detaches the QImage from the numpy buffer — otherwise the
        # underlying memory gets freed before Qt is finished reading.
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self.preview.set_frame(QPixmap.fromImage(qimg), w, h)

    def _update_scrubber(self) -> None:
        if not self.duration:
            return
        pct = self.current_t / self.duration
        self.scrubber.set_position(pct)
        in_pct  = self.mark_in  / self.duration if self.duration else 0.0
        out_pct = self.mark_out / self.duration if self.duration else 1.0
        self.scrubber.set_markers(in_pct, out_pct)
        self.timecode.setText(f"{self._fmt_hms(self.current_t)} / {self._fmt_hms(self.duration)}")
        if self.mark_in > 0:
            self.in_label.setText(f"In: {self._fmt_hms(self.mark_in)}")
        if self.mark_out < self.duration:
            self.out_label.setText(f"Out: {self._fmt_hms(self.mark_out)}")

    @staticmethod
    def _fmt_hms(s: float) -> str:
        return f"{int(s//3600):02d}:{int(s%3600//60):02d}:{int(s%60):02d}"

    def _on_scrubber_hover(self, t: float, x: int, global_y: int) -> None:
        if not self._hover_label:
            return

        if t < 0:
            # Fade out
            try:
                self._hover_anim.finished.disconnect()
            except TypeError:
                pass
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._hover_opacity.opacity())
            self._hover_anim.setEndValue(0.0)
            self._hover_anim.finished.connect(self._hover_label.hide)
            self._hover_anim.start()
            self._hover_above = None
            return

        # Format time
        total = max(0.0, t)
        h = int(total // 3600)
        m = int(total % 3600 // 60)
        s = int(total % 60)
        sub = total % 1
        fps = self.fps or 30.0
        if self._hover_show_frames:
            fps_base = round(fps) if abs(fps - round(fps)) < 0.5 else int(fps)
            if fps_base <= 0:
                fps_base = 30
            frame_in_sec = int(total * fps_base) % fps_base
            sub_str = f"  [F{frame_in_sec:02d}]"
        else:
            sub_str = f".{int(sub * 100):02d}"
        self._hover_label.setText(f"{h:02d}:{m:02d}:{s:02d}{sub_str}")
        self._hover_label.adjustSize()

        scrubber_tl = self.scrubber.mapTo(self.centralWidget(), QPoint(0, 0))
        scrubber_mid_g = self.scrubber.mapToGlobal(
            QPoint(0, self.scrubber.height() // 2),
        ).y()

        lw = self._hover_label.width()
        lh = self._hover_label.height()
        above = global_y > scrubber_mid_g

        if above:
            ly = scrubber_tl.y() - lh - 6
        else:
            ly = scrubber_tl.y() + self.scrubber.height() + 6

        cw = self.centralWidget().width()
        lx = scrubber_tl.x() + max(4, min(x - lw // 2, self.scrubber.width() - lw - 4))
        lx = max(4, min(lx, cw - lw - 4))
        self._hover_label.move(lx, ly)
        self._hover_label.raise_()

        side_changed = (self._hover_above != above)
        self._hover_above = above

        try:
            self._hover_anim.finished.disconnect()
        except TypeError:
            pass
        self._hover_anim.stop()

        if not self._hover_label.isVisible() or side_changed:
            self._hover_opacity.setOpacity(0.0)
            self._hover_label.show()
            self._hover_anim.setStartValue(0.0)
            self._hover_anim.setEndValue(1.0)
            self._hover_anim.start()
        else:
            self._hover_opacity.setOpacity(1.0)

    # =============================================================
    # Section 3 — Crop, Mark In/Out, clips, undo/redo
    # =============================================================
    def _on_crop_drawn(self, cr: dict) -> None:
        self.crop_rect = cr  # type: ignore[assignment]
        self.btn_crop.setChecked(False)
        self._update_crop_ui()

    def _on_crop_fields_changed(self) -> None:
        sb = self.sidebar
        x, y = sb.crop_x.value(), sb.crop_y.value()
        w, h = sb.crop_w.value(), sb.crop_h.value()
        if w >= 2 and h >= 2:
            self.crop_rect = {"x": x, "y": y, "w": w, "h": h}
            self.preview.set_crop_from_video(x, y, w, h)
            self._update_crop_info()
            sb.btn_ex_crop.setEnabled(True)
            self.btn_crop_clr.setEnabled(True)

    def _update_crop_ui(self) -> None:
        if not self.crop_rect:
            return
        cr = self.crop_rect
        sb = self.sidebar
        for sp, val in (
            (sb.crop_x, cr["x"]), (sb.crop_y, cr["y"]),
            (sb.crop_w, cr["w"]), (sb.crop_h, cr["h"]),
        ):
            sp.blockSignals(True); sp.setValue(val); sp.blockSignals(False)
        self.preview.set_crop_from_video(cr["x"], cr["y"], cr["w"], cr["h"])
        self._update_crop_info()
        sb.btn_ex_crop.setEnabled(True)
        self.btn_crop_clr.setEnabled(True)

    def _update_crop_info(self) -> None:
        if self.crop_rect:
            cr = self.crop_rect
            self.sidebar.crop_info.setText(f"{cr['w']}×{cr['h']}  @  {cr['x']}, {cr['y']}")
            self.sidebar.crop_info.setStyleSheet(f"color:{ACC3}; font-size:10px;")
        else:
            self.sidebar.crop_info.setText("No crop — draw on preview or enter values")
            self.sidebar.crop_info.setStyleSheet(f"color:{MUTED2}; font-size:10px;")

    def _clear_crop(self) -> None:
        self.crop_rect = None
        self.preview.clear_crop()
        sb = self.sidebar
        for sp in (sb.crop_x, sb.crop_y, sb.crop_w, sb.crop_h):
            sp.blockSignals(True); sp.setValue(0); sp.blockSignals(False)
        self._update_crop_info()
        sb.btn_ex_crop.setEnabled(False)
        self.btn_crop_clr.setEnabled(False)

    def _set_crop_preset(self, wr: int, hr: int) -> None:
        if not self.vid_w:
            return
        if self.vid_w / self.vid_h > wr / hr:
            h = self.vid_h; w = int(h * wr / hr)
        else:
            w = self.vid_w; h = int(w * hr / wr)
        w -= w % 2; h -= h % 2
        x = (self.vid_w - w) // 2
        y = (self.vid_h - h) // 2
        self.crop_rect = {"x": x, "y": y, "w": w, "h": h}
        self._update_crop_ui()

    # ── Mark In/Out ─────────────────────────────────────────────────
    def _set_mark(self, which: str) -> None:
        if not self.video_path:
            return
        t = self.current_t
        if which == "in":
            self.mark_in = t
            self.sidebar.mark_in_spin.blockSignals(True)
            self.sidebar.mark_in_spin.setValue(t)
            self.sidebar.mark_in_spin.blockSignals(False)
        else:
            self.mark_out = t
            self.sidebar.mark_out_spin.blockSignals(True)
            self.sidebar.mark_out_spin.setValue(t)
            self.sidebar.mark_out_spin.blockSignals(False)
        self._update_scrubber()

    # ── Clip CRUD ──────────────────────────────────────────────────
    def _add_clip(self) -> None:
        if not self.video_path:
            return
        s = self.sidebar.mark_in_spin.value()
        e = self.sidebar.mark_out_spin.value()
        if e <= s:
            QMessageBox.warning(self, "Klipwerk", "Out must be after In")
            return
        # Shallow-copy the crop dict so later UI edits don't mutate this clip's crop.
        # cast() is for the type-checker; at runtime it's a plain dict.
        from typing import cast
        clip_crop: CropRect | None = (
            cast(CropRect, dict(self.crop_rect)) if self.crop_rect else None
        )
        clip = Clip(
            name=f"{self._k('Klip')} {len(self.clips) + 1}",
            start=s, end=e,
            crop=clip_crop,
        )
        self.history.add(clip)
        self._render_clips()
        self._render_timeline()

    def _del_clip(self, idx: int) -> None:
        if not (0 <= idx < len(self.clips)):
            return
        self.history.delete(idx)
        if self.active_clip >= len(self.clips):
            self.active_clip = len(self.clips) - 1
        self._render_clips()
        self._render_timeline()

    def _delete_active_clip(self) -> None:
        if 0 <= self.active_clip < len(self.clips):
            self._del_clip(self.active_clip)

    def _rename_clip(self, idx: int) -> None:
        if not (0 <= idx < len(self.clips)):
            return
        name, ok = QInputDialog.getText(
            self, "Klip umbenennen", "Name:",
            text=self.clips[idx].name,
        )
        if ok and name.strip():
            self.history.rename(idx, name.strip())
            self._render_clips()
            self._render_timeline()

    def _sel_clip(self, idx: int) -> None:
        if not (0 <= idx < len(self.clips)):
            return
        self.active_clip = idx
        self._seek_to(self.clips[idx].start)
        self._render_clips()
        self._render_timeline()
        self.sidebar.btn_ex_clip.setEnabled(True)
        self._update_fname_preview()

    def _preview_clip(self, idx: int) -> None:
        if not (0 <= idx < len(self.clips)):
            return
        self._seek_to(self.clips[idx].start)
        if not self.playing:
            self._play()

    def _preview_sequence(self) -> None:
        if not self.clips or not self.video_path:
            return
        self._seq_active = True
        self._seq_idx = 0
        self._stop(cancel_seq=False)
        self._jump_to_seq_clip(0)

    def _jump_to_seq_clip(self, idx: int) -> None:
        if idx >= len(self.clips):
            self._seq_active = False
            self._seq_idx = -1
            self._stop(cancel_seq=False)
            self._set_status("ready", ACC)
            return
        self._seq_idx = idx
        self.active_clip = idx
        self._render_clips()
        self._render_timeline()
        c = self.clips[idx]
        self._stop(cancel_seq=False)
        self._seek_to(c.start)
        self._play()
        self._set_status(
            f"preview: {c.name}  ({idx + 1}/{len(self.clips)} {self._k('Klips')})",
            ACC3,
        )

    def _move_clip(self, from_idx: int, to_idx: int) -> None:
        if self.history.move(from_idx, to_idx):
            self.active_clip = to_idx
            self._render_clips()
            self._render_timeline()

    def _undo(self) -> None:
        if self.history.undo():
            self.active_clip = min(self.active_clip, len(self.clips) - 1)
            self._render_clips()
            self._render_timeline()
            self._set_status(f"undo  ({self.history.undo_depth} left)", MUTED2)

    def _redo(self) -> None:
        if self.history.redo():
            self.active_clip = min(self.active_clip, len(self.clips) - 1)
            self._render_clips()
            self._render_timeline()
            self._set_status(f"redo  ({self.history.redo_depth} left)", MUTED2)

    # ── Rendering — incremental diff instead of wipe-and-rebuild ──
    def _render_clips(self) -> None:
        """Reconcile sidebar clip rows against the current clip list."""
        layout = self.sidebar.clips_vlay

        # Strip stretcher + all old widgets
        while layout.count():
            layout_item = layout.takeAt(0)
            if layout_item is None:
                continue
            old_widget = layout_item.widget()
            if old_widget is not None:
                old_widget.setParent(None)
        self._clip_items.clear()

        k = self._k
        if not self.clips:
            layout.addWidget(label(f"No {k('Klips')} yet", color=MUTED, size=12))
            self.sidebar.clips_count_label.setText(f"0 {k('Klips')}")
        else:
            n = len(self.clips)
            plural = "s" if n != 1 else ""
            self.sidebar.clips_count_label.setText(f"{n} {k('klip')}{plural}")
            for i, c in enumerate(self.clips):
                clip_item = ClipItem(c, i, self.duration)
                clip_item.selected.connect(self._sel_clip)
                clip_item.deleted.connect(self._del_clip)
                clip_item.renamed.connect(self._rename_clip)
                clip_item.set_active(i == self.active_clip)
                self._clip_items[c.id] = clip_item
                layout.addWidget(clip_item)

        layout.addStretch()
        self.sidebar.btn_ex_seq.setEnabled(len(self.clips) >= 2)
        self.btn_preview_seq.setEnabled(len(self.clips) >= 1)
        if self.active_clip < 0 or self.active_clip >= len(self.clips):
            self.sidebar.btn_ex_clip.setEnabled(False)

    def _render_timeline(self) -> None:
        while self.tl_lay.count():
            layout_item = self.tl_lay.takeAt(0)
            if layout_item is None:
                continue
            old_widget = layout_item.widget()
            if old_widget is not None:
                old_widget.setParent(None)
        self._timeline_items.clear()

        k = self._k
        if not self.clips:
            self.tl_lay.addWidget(label(f"No {k('Klips')}", color=MUTED, size=11))
        else:
            for i, c in enumerate(self.clips):
                width = max(70, int(c.duration * 30))
                tc = TimelineClip(c, i, width)
                tc.clicked.connect(self._sel_clip)
                tc.moved.connect(self._move_clip)
                tc.previewed.connect(self._preview_clip)
                tc.renamed.connect(self._rename_clip)
                tc.set_active(i == self.active_clip)
                self._timeline_items[c.id] = tc
                self.tl_lay.addWidget(tc)
            n = len(self.clips)
            plural = "s" if n != 1 else ""
            self.tl_info.setText(
                f"{n} {k('klip')}{plural} — drag {k('Klips')} to reorder",
            )

        total_w = sum(max(70, int(c.duration * 30)) + 5 for c in self.clips) + 20
        self.tl_container.setFixedWidth(max(self.tl_scroll.width(), total_w))

    # =============================================================
    # Section 4 — Filenames, codec note, export
    # =============================================================
    def _build_out_stem(self, core: str, mode_suf: str = "") -> str:
        pre = self.sidebar.export_prefix.text().strip()
        return _sanitize(pre) + _sanitize(core) + _sanitize(mode_suf)

    def _update_fname_preview(self) -> None:
        if not self.video_path:
            self.sidebar.fname_preview.setText("")
            self.sidebar.fname_preview_crop.setText("")
            return
        sb  = self.sidebar
        fmt = self._current_format().container
        stem = Path(self.video_path).stem

        crop_out = self._build_out_stem(stem, sb.export_suffix_crop.text().strip())
        clip_out = self._build_out_stem(stem, sb.export_suffix_clip.text().strip())
        seq_out  = self._build_out_stem(stem, sb.export_suffix_seq.text().strip())

        sb.fname_preview_crop.setText(f"→  {crop_out}.{fmt}")
        sb.fname_preview.setText(
            f"crop:  {crop_out}.{fmt}\n"
            f"{self._k('klip')}:  {clip_out}.{fmt}\n"
            f"seq:   {seq_out}.{fmt}"
        )

    def _current_format(self):
        return FORMATS[self.sidebar.export_fmt.currentIndex()]

    def _on_fmt_changed(self, idx: int) -> None:
        spec = FORMATS[idx]
        sb = self.sidebar
        sb.export_crf.blockSignals(True)
        sb.export_crf.setRange(0, spec.crf_max)
        sb.export_crf.setValue(spec.crf_default)
        sb.export_crf.blockSignals(False)

        sb.export_preset.blockSignals(True)
        sb.export_preset.clear()
        sb.export_preset.addItems(list(spec.presets))
        sb.export_preset.setCurrentIndex(len(spec.presets) // 2)
        sb.export_preset.blockSignals(False)

        self._update_codec_note(idx)
        self._update_fname_preview()

    def _update_codec_note(self, idx: int) -> None:
        if 0 <= idx < len(FORMATS):
            self.sidebar.codec_note.setText(FORMATS[idx].note)

    def _crop_vf(self, cr: CropRect | None) -> list[str]:
        # Thin wrapper around the shared builder — kept as a method so
        # internal callers keep working. Duplicating the even-pixel
        # rounding rule in two places was the sort of thing that bit us
        # the last time (the double _update_codec_note), so: one source.
        return crop_vf_args(cr)

    def _codec_ffmpeg_args(self) -> list[str]:
        spec = self._current_format()
        crf = self.sidebar.export_crf.value()
        preset = self.sidebar.export_preset.currentText()
        return codec_args(spec, crf, preset)

    def _export(self, mode: str) -> None:
        if not self.video_path:
            return
        if mode == "crop" and not self.crop_rect:
            QMessageBox.warning(self, "Klipwerk", "Kein Crop ausgewählt.")
            return
        if mode == "clip" and not (0 <= self.active_clip < len(self.clips)):
            QMessageBox.warning(self, "Klipwerk", "Kein Klip ausgewählt.")
            return
        if mode == "sequence" and len(self.clips) < 2:
            QMessageBox.warning(self, "Klipwerk", "Mindestens 2 Klips für Sequence-Export benötigt.")
            return

        spec = self._current_format()
        fmt = spec.container
        out_dir = Path(self.video_path).parent
        stem = Path(self.video_path).stem

        sb = self.sidebar
        mode_suf = {
            "crop":     sb.export_suffix_crop.text().strip(),
            "clip":     sb.export_suffix_clip.text().strip(),
            "sequence": sb.export_suffix_seq.text().strip(),
        }
        suggested = self._build_out_stem(stem, mode_suf.get(mode, ""))

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save As", str(out_dir / f"{suggested}.{fmt}"),
            f"Video (*.{fmt})",
        )
        if not out_path:
            return

        self._stop()
        src = self.video_path
        codec = self._codec_ffmpeg_args()

        if mode == "crop":
            cmd = [
                ffmpeg_bin(), "-y", "-i", src,
                *self._crop_vf(self.crop_rect),
                *codec, out_path,
            ]
            self._run_simple_export(cmd, out_path)

        elif mode == "clip":
            c = self.clips[self.active_clip]
            cmd = [
                ffmpeg_bin(), "-y",
                "-ss", str(c.start), "-i", src, "-t", str(c.duration),
                *self._crop_vf(c.crop),
                *codec, out_path,
            ]
            self._run_simple_export(cmd, out_path)

        elif mode == "sequence":
            self._run_sequence_export(src, out_path, codec)

    def _run_simple_export(self, cmd: list[str], out_path: str) -> None:
        worker = FFmpegWorker(cmd, out_path, parent=self)
        self._run_worker(worker, out_path)

    def _run_sequence_export(self, src: str, out_path: str, codec: list[str]) -> None:
        tmp = Path(out_path).parent / f"_klipwerk_tmp_{uuid.uuid4().hex[:8]}"
        tmp.mkdir(exist_ok=True)

        # All planning logic lives in core.export_builder so it's
        # testable without Qt. This method just wires the plan into a
        # worker and the progress dialog.
        plan = plan_sequence_export(
            clips=self.clips,
            src_path=src,
            out_path=out_path,
            codec_args=codec,
            target_container=self._current_format().container,
            ffmpeg=ffmpeg_bin(),
            tmp_dir=tmp,
        )

        worker = SequenceFFmpegWorker(
            plan.segment_cmds, plan.concat_cmd, plan.list_file, out_path, parent=self,
        )
        self._run_worker(worker, out_path, cleanup_dir=tmp, status=plan.status_text)

    def _run_worker(
        self,
        worker: FFmpegWorker,
        out_path: str,
        cleanup_dir: Path | None = None,
        status: str = "exporting…",
    ) -> None:
        self._set_status(status, "#f90")

        prog = QProgressDialog("Exporting…", "Cancel", 0, 100, self)
        prog.setWindowTitle("Klipwerk — Export")
        prog.setStyleSheet(STYLE)
        prog.setMinimumWidth(360)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.show()

        def cleanup():
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

        def on_progress(pct: int, text: str) -> None:
            prog.setValue(pct)
            prog.setLabelText(text)

        def on_done(path: str) -> None:
            prog.setValue(100)
            prog.close()
            self._set_status("ready", ACC)
            cleanup()
            QMessageBox.information(
                self, "Klipwerk — Done", f"Export saved:\n{path}",
            )

        def on_error(msg: str) -> None:
            prog.close()
            self._set_status("error", ACC2)
            cleanup()
            QMessageBox.critical(
                self, "Klipwerk — Export Error", f"FFmpeg error:\n\n{msg}",
            )

        def on_canceled() -> None:
            worker.cancel()
            self._set_status("canceled", MUTED2)
            cleanup()

        prog.canceled.connect(on_canceled)
        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.error.connect(on_error)

        self._worker = worker
        worker.start()

    # =============================================================
    # Frameless-window event handling
    # =============================================================
    def eventFilter(self, obj, event):
        from PyQt6.QtWidgets import QAbstractScrollArea, QScrollBar

        if event.type() == QEvent.Type.Polish and isinstance(obj, QScrollBar):
            obj.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            return False

        if event.type() == QEvent.Type.MouseMove:
            widget_under = None
            try:
                widget_under = QApplication.widgetAt(event.globalPosition().toPoint())
            except (AttributeError, RuntimeError):
                pass
            is_scrollbar = isinstance(widget_under, (QScrollBar, QAbstractScrollArea))

            if not self._resizing and not self._drag_pos and not is_scrollbar:
                try:
                    gpos = event.globalPosition().toPoint()
                    local = self.mapFromGlobal(gpos)
                    d = self._get_resize_dir(local)
                    cursors = {
                        "left":         Qt.CursorShape.SizeHorCursor,
                        "right":        Qt.CursorShape.SizeHorCursor,
                        "top":          Qt.CursorShape.SizeVerCursor,
                        "bottom":       Qt.CursorShape.SizeVerCursor,
                        "top-left":     Qt.CursorShape.SizeFDiagCursor,
                        "top-right":    Qt.CursorShape.SizeBDiagCursor,
                        "bottom-left":  Qt.CursorShape.SizeBDiagCursor,
                        "bottom-right": Qt.CursorShape.SizeFDiagCursor,
                    }
                    if d:
                        QApplication.setOverrideCursor(QCursor(cursors[d]))
                    else:
                        QApplication.restoreOverrideCursor()
                except (AttributeError, RuntimeError):
                    pass
            elif is_scrollbar:
                QApplication.restoreOverrideCursor()

            if self._resizing and (event.buttons() & Qt.MouseButton.LeftButton):
                self._do_resize(event.globalPosition().toPoint())

        elif event.type() == QEvent.Type.MouseButtonRelease and self._resizing:
            self._resizing = False
            self._resize_dir = None
            QApplication.restoreOverrideCursor()

        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        in_titlebar = self._titlebar.geometry().contains(pos)
        if in_titlebar and not self.isMaximized():
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        else:
            self._drag_pos = None
        self._resize_dir = self._get_resize_dir(pos)
        if self._resize_dir:
            self._resizing = True
            self._resize_start_geo = self.geometry()
            self._resize_start_pos = event.globalPosition().toPoint()
            QApplication.restoreOverrideCursor()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_pos = None
        self._resizing = False
        self._resize_dir = None

    def mouseDoubleClickEvent(self, event) -> None:
        if self._titlebar.geometry().contains(event.position().toPoint()):
            self._toggle_maximize()

    def _get_resize_dir(self, pos: QPoint) -> str | None:
        if self.isMaximized():
            return None
        m = self._RESIZE_MARGIN
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        left, right = x < m, x > w - m
        top, bottom = y < m, y > h - m
        if top and left:  return "top-left"
        if top and right: return "top-right"
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
        if "left" in d:
            geo.setLeft(min(geo.left() + delta.x(), geo.right() - min_w))
        if "right" in d:
            geo.setRight(max(geo.right() + delta.x(), geo.left() + min_w))
        if "top" in d:
            geo.setTop(min(geo.top() + delta.y(), geo.bottom() - min_h))
        if "bottom" in d:
            geo.setBottom(max(geo.bottom() + delta.y(), geo.top() + min_h))
        # Resize goes through setGeometry which triggers a full layout
        # + paint cycle on every mouse-move event. On Windows the
        # compositor does its own DWM work on top, so we see visible
        # flicker. Qt's resize() is slightly cheaper than setGeometry()
        # when the position isn't changing — split the two cases so the
        # common "drag the bottom-right corner" path doesn't reposition.
        if geo.topLeft() == self._resize_start_geo.topLeft():
            self.resize(geo.size())
        else:
            self.setGeometry(geo)

    # ── Status + cleanup ────────────────────────────────────────────
    def _set_status(self, text: str, color: str = ACC) -> None:
        self.status_label.setText(text)
        self.status_dot.setStyleSheet(
            f"color:{color}; font-size:8px; background:transparent;"
        )

    # ── Settings persistence ────────────────────────────────────────
    def _apply_settings(self) -> None:
        """Restore persisted user preferences onto the freshly-built UI.

        Load order matters: selecting a new export format fires
        ``_on_fmt_changed`` which stomps CRF+preset with that format's
        defaults. So we set the format *first*, then overwrite CRF /
        preset with the saved values (validated against the format's
        own range / preset list — stale configs must not wedge the UI).
        """
        s = self.settings

        # Geometry — Qt's opaque blob handles size, pos, maximized state.
        blob = s.geometry()
        if blob is not None:
            self.restoreGeometry(blob)

        # Filename prefix / per-mode suffixes — plain text, no signal cascade.
        self.sidebar.export_prefix.setText(s.prefix(default=""))
        self.sidebar.export_suffix_crop.setText(s.suffix_crop(default="_crop"))
        self.sidebar.export_suffix_clip.setText(s.suffix_clip(default="_clip"))
        self.sidebar.export_suffix_seq.setText(s.suffix_seq(default="_seq"))

        # Format → this triggers _on_fmt_changed and overwrites
        # CRF / preset with the format's defaults.
        saved_fmt = s.fmt_index(default=0)
        if 0 <= saved_fmt < len(FORMATS):
            self.sidebar.export_fmt.setCurrentIndex(saved_fmt)

        # Now restore CRF / preset on top of those defaults, guarded
        # against stale values that would be invalid for the format.
        spec = FORMATS[self.sidebar.export_fmt.currentIndex()]

        saved_crf = s.crf(default=spec.crf_default)
        if 0 <= saved_crf <= spec.crf_max:
            self.sidebar.export_crf.blockSignals(True)
            self.sidebar.export_crf.setValue(saved_crf)
            self.sidebar.export_crf.blockSignals(False)

        saved_preset = s.preset(default="")
        if saved_preset in spec.presets:
            self.sidebar.export_preset.blockSignals(True)
            self.sidebar.export_preset.setCurrentText(saved_preset)
            self.sidebar.export_preset.blockSignals(False)

        # K/C mode — only flip if it differs, so we don't fire the
        # toggled signal uselessly and trigger a relabel+rerender.
        use_k = s.use_k_mode(default=True)
        if use_k != self._use_k_mode:
            self.btn_klip_toggle.setChecked(use_k)

        # Sidebar splitter — restore the user's last preferred size
        # distribution between the three panels. `restoreState` returns
        # False (or silently no-ops) if the saved blob is from a
        # different child-count / Qt version — in that case the
        # splitter falls back to its initial setSizes() values, which
        # is fine.
        split_blob = s.sidebar_splitter()
        if split_blob is not None:
            try:
                ok = self.sidebar.sections_splitter.restoreState(split_blob)
                if not ok:
                    log.debug("sidebar_splitter state could not be restored; using defaults")
            except (RuntimeError, ValueError) as e:
                log.debug("sidebar_splitter restore failed: %s", e)

        # Final fname preview reflects restored prefix/suffix.
        self._update_fname_preview()

    def _save_settings(self) -> None:
        """Write current UI state out for the next session."""
        s = self.settings
        s.set_geometry(self.saveGeometry())
        s.set_prefix(self.sidebar.export_prefix.text())
        s.set_suffix_crop(self.sidebar.export_suffix_crop.text())
        s.set_suffix_clip(self.sidebar.export_suffix_clip.text())
        s.set_suffix_seq(self.sidebar.export_suffix_seq.text())
        s.set_fmt_index(self.sidebar.export_fmt.currentIndex())
        s.set_crf(self.sidebar.export_crf.value())
        s.set_preset(self.sidebar.export_preset.currentText())
        s.set_use_k_mode(self._use_k_mode)
        s.set_sidebar_splitter(self.sidebar.sections_splitter.saveState())

    def closeEvent(self, event) -> None:
        # Persist first — if QSettings can't write for some OS reason,
        # we still want the worker cleanup below to run.
        try:
            self._save_settings()
        except Exception:
            log.exception("failed to save settings")

        if self.cap:
            self.cap.release()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        if self._waveform_worker and self._waveform_worker.isRunning():
            self._waveform_worker.cancel()
            self._waveform_worker.wait(500)
        event.accept()
