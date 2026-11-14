"""Sky's visual theme: deep navy and black with cyan accents."""
from __future__ import annotations

COLORS = {
    "bg": "#050A12",  # window background (near black)
    "panel": "#0A1424",  # raised panels and the input box
    "border": "#12304A",
    "border_dim": "#0E2133",
    "text": "#D6E8F5",
    "muted": "#6F8BA4",
    "cyan": "#00E5FF",
    "cyan_hover": "#4DF0FF",
    "cyan_dim": "#0E3A45",
    "blue": "#2979FF",
    "user": "#8FE3FF",
    "error": "#FF5C7A",
    "warning": "#FFB84D",
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

QLabel#title {{ color: {c['cyan']}; font-size: 16pt; font-weight: 600; }}
QLabel#model {{ color: {c['muted']}; font-family: {FONT_MONO}; font-size: 9pt; }}
QLabel#stateLabel {{ color: {c['cyan']}; font-size: 9pt; font-weight: 600; }}
QLabel#status {{ color: {c['muted']}; font-family: {FONT_MONO}; font-size: 9pt; }}

QTextEdit#transcript {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 10px;
    selection-background-color: {c['blue']};
}}

QLineEdit#input {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 10px 12px;
    selection-background-color: {c['blue']};
}}
QLineEdit#input:focus {{ border: 1px solid {c['cyan']}; }}

QPushButton {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 9px 16px;
}}
QPushButton:hover {{ border-color: {c['cyan']}; }}
QPushButton:disabled {{
    background-color: {c['bg']};
    border-color: {c['border_dim']};
    color: {c['muted']};
}}
QPushButton[role="primary"] {{
    background-color: {c['cyan']};
    color: #02121A;
    border: none;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {c['cyan_hover']}; }}
QPushButton[role="primary"]:disabled {{ background-color: {c['cyan_dim']}; color: #4B7A86; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {c['blue']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QToolTip {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['cyan']};
    padding: 4px;
}}
"""
