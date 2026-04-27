"""Color palette and global Qt stylesheet.

These values used to live at module scope in the monolithic script. They
are intentionally kept as simple module-level constants rather than an
enum / dataclass — they're string fragments interpolated into f-strings
hundreds of times and that's the shape that reads best.
"""
from __future__ import annotations

# ── Palette ──────────────────────────────────────────────────────────────
BG      = "#080809"
S1      = "#0f0f12"
S2      = "#16161c"
S3      = "#1e1e26"
BORDER  = "#252530"
BORDER2 = "#32323f"
ACC     = "#c8f53a"   # lime — primary accent
ACC2    = "#ff3d5a"   # red  — destructive / out-marker
ACC3    = "#3df5c8"   # cyan — info / in-marker
TEXT    = "#e2e2ec"
MUTED   = "#52526a"
MUTED2  = "#72728a"


STYLE = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}

/* Buttons — explicit color on all states to prevent OS overrides */
QPushButton {{
    background: {S3};
    border: 2px solid {BORDER2};
    color: {TEXT};
    padding: 6px 14px;
    border-radius: 4px;
    font-size: 12px;
    min-height: 26px;
    outline: none;
}}
QPushButton:hover  {{ border-color: {ACC}; color: {ACC}; background: {S3}; }}
QPushButton:pressed {{ background: {S2}; color: {TEXT}; border-color: {BORDER2}; }}
QPushButton:focus  {{ outline: none; border-color: {BORDER2}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: {S2}; }}

QPushButton#accent {{
    background: {ACC}; color: #000;
    border-color: {ACC}; font-weight: bold; font-size: 12px;
}}
QPushButton#accent:hover  {{ background: #d4ff45; border-color: #d4ff45; color: #000; }}
QPushButton#accent:pressed {{ background: #b8e030; color: #000; }}
QPushButton#accent:focus   {{ outline: none; background: {ACC}; color: #000; }}
QPushButton#accent:disabled {{ background: {S3}; color: {MUTED}; border-color: {BORDER}; }}

QPushButton#danger {{ color: {TEXT}; background: {S3}; }}
QPushButton#danger:hover {{ border-color: {ACC2}; color: {ACC2}; background: {S3}; }}
QPushButton#danger:focus {{ outline: none; }}

/* Compact variant — used in the top toolbar so button heights line
   up with the small C/K and Tips toggles. Overrides padding and
   min-height from the base rule; colour/border stay inherited. */
QPushButton[compact="true"] {{
    padding: 4px 10px;
    font-size: 11px;
    min-height: 0px;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 5px; background: {S3}; border-radius: 3px; border: 1px solid {BORDER2};
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0;
    background: {ACC}; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {ACC}; border-radius: 3px; }}

/* Inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {S3}; border: 1px solid {BORDER2};
    color: {TEXT}; padding: 4px 7px; border-radius: 5px;
    font-size: 12px; min-height: 24px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACC}; outline: none;
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ width: 9px; }}
QComboBox QAbstractItemView {{
    background: {S2}; border: 1px solid {BORDER2};
    color: {TEXT}; selection-background-color: {S3};
    padding: 4px; outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {S2}; border: none; width: 18px;
}}

/* Scrollbar */
QScrollBar:vertical {{
    background: {S2}; width: 8px; border: none;
}}
QScrollBar::handle:vertical {{
    background: {ACC}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: {S2};
}}
QScrollBar:horizontal {{
    background: {S2}; height: 8px; border: none;
}}
QScrollBar::handle:horizontal {{
    background: {ACC}; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: {S2};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

/* Frames */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {BORDER}; }}
QScrollArea {{ border: none; }}

/* Splitter */
QSplitter::handle:horizontal {{ background: {BORDER2}; width: 4px; }}
QSplitter::handle:horizontal:hover {{ background: {ACC}; }}

/* Tooltips */
QToolTip {{
    background: {S2};
    color: {TEXT};
    border: 1px solid {ACC3};
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 11px;
    font-family: 'Consolas', 'Courier New', monospace;
    opacity: 240;
}}
"""
