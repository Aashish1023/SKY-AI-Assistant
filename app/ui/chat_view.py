"""The conversation transcript.

Text streams in token by token. The view follows the newest text only while you
are already at the bottom, so scrolling up to re-read something is never
interrupted by a new answer.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget

from app.ui.theme import COLORS

AT_BOTTOM_TOLERANCE_PX = 4


def _format(
    color: str,
    *,
    bold: bool = False,
    italic: bool = False,
    point_size: float | None = None,
    letter_spacing: int | None = None,
) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    fmt.setFontItalic(italic)
    if point_size is not None:
        fmt.setFontPointSize(point_size)
    if letter_spacing is not None:
        fmt.setFontLetterSpacingType(QFont.SpacingType.PercentageSpacing)
        fmt.setFontLetterSpacing(letter_spacing)
    return fmt


class ChatView(QTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transcript")
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self._sky_message_open = False

        self._user_label = _format(COLORS["muted"], bold=True, point_size=8.5, letter_spacing=130)
        self._sky_label = _format(COLORS["cyan"], bold=True, point_size=8.5, letter_spacing=130)
        self._user_text = _format(COLORS["user"])
        self._sky_text = _format(COLORS["text"])
        self._notice_formats = {
            "info": _format(COLORS["muted"], italic=True),
            "warning": _format(COLORS["warning"], italic=True),
            "error": _format(COLORS["error"]),
        }

    # -- public API --------------------------------------------------------
    def add_user_message(self, text: str, label: str = "YOU") -> None:
        self.end_sky_message()
        self._write(f"{label}\n", self._user_label)
        self._write(f"{text}\n\n", self._user_text)

    def append_sky_text(self, text: str, label: str = "SKY") -> None:
        """Add streamed answer text. The first piece also writes the speaker label."""
        if not self._sky_message_open:
            self._write(f"{label}\n", self._sky_label)
            self._sky_message_open = True
        self._write(text, self._sky_text)

    def end_sky_message(self) -> None:
        if self._sky_message_open:
            self._write("\n\n", self._sky_text)
            self._sky_message_open = False

    def add_notice(self, text: str, kind: str = "info") -> None:
        self.end_sky_message()
        self._write(f"{text}\n\n", self._notice_formats.get(kind, self._notice_formats["info"]))

    def clear_transcript(self) -> None:
        self.clear()
        self._sky_message_open = False

    def plain_text(self) -> str:
        return self.toPlainText()

    # -- internals ---------------------------------------------------------
    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - AT_BOTTOM_TOLERANCE_PX

    def _write(self, text: str, fmt: QTextCharFormat) -> None:
        follow = self._at_bottom()
        cursor = QTextCursor(self.document())  # a private cursor: the user's selection is untouched
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, fmt)
        if follow:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())
