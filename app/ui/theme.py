"""Sky's visual theme: deep navy and black with cyan accents."""
from __future__ import annotations

COLORS = {
    "bg": "#0B0508",  # window background (near black, a hint of red)
    "panel": "#150A0F",  # raised panels and the input box
    "border": "#3A1420",
    "border_dim": "#26101A",
    "text": "#F2DEE2",
    "muted": "#9C7A84",
    "accent": "#FF2E4D",  # the main red
    "accent_hover": "#FF6B80",
    "accent_dim": "#4A1420",
    "accent2": "#C1121F",  # deeper crimson, for secondary details
    "user": "#FFB3C0",  # your own messages: soft pink
    "error": "#FF8A3D",  # orange, so errors stand out from the red accent
    "warning": "#FFD166",
    "ok": "#3DDC97",
}

FONT_UI = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
FONT_MONO = '"Cascadia Mono", Consolas, "Courier New", monospace'
 
 
def build_stylesheet() -> str:
    """The Qt style sheet for the whole application."""
    c = COLORS
    return f"""
QMainWindow, QWidget#root {{ background-color: {c['bg']}; }}
QWidget {{ color: {c['text']}; font-family: {FONT_UI}; font-size: 10.5pt; }}
 
QLabel#title {{ color: {c['accent']}; font-size: 16pt; font-weight: 600; }}
QLabel#model {{ color: {c['muted']}; font-family: {FONT_MONO}; font-size: 9pt; }}
QLabel#stateLabel {{ color: {c['accent']}; font-size: 9pt; font-weight: 600; }}
QLabel#status {{ color: {c['muted']}; font-family: {FONT_MONO}; font-size: 9pt; }}
 
QTextEdit#transcript {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 10px;
    selection-background-color: {c['accent2']};
}}
 
QLineEdit#input {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 10px 12px;
    selection-background-color: {c['accent2']};
}}
QLineEdit#input:focus {{ border: 1px solid {c['accent']}; }}
 
QPushButton {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 9px 16px;
}}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:disabled {{
    background-color: {c['bg']};
    border-color: {c['border_dim']};
    color: {c['muted']};
}}
QPushButton[role="primary"] {{
    background-color: {c['accent']};
    color: #FFFFFF;
    border: none;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {c['accent_hover']}; }}
QPushButton[role="primary"]:disabled {{ background-color: {c['accent_dim']}; color: #8A5560; }}
 
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['accent2']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
 
QToolTip {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['accent']};
    padding: 4px;
}}
"""