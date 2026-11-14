"""The animated circular assistant visualization (the "orb").

It is drawn with QPainter, so it needs no image files, and it is deliberately
cheap to run:
  * it animates at ~12 frames per second while Sky is idle and ~30 while it works,
  * it stops completely while the window is hidden or minimized.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.core.events import AssistantState
from app.ui.theme import COLORS

FRAME_INTERVAL_MS = {
    AssistantState.IDLE: 80,
    AssistantState.THINKING: 33,
    AssistantState.RESPONDING: 33,
}
ROTATION_DEG_PER_S = {
    AssistantState.IDLE: 8.0,
    AssistantState.THINKING: 120.0,
    AssistantState.RESPONDING: 45.0,
}
PULSE_RAD_PER_S = {
    AssistantState.IDLE: 1.2,
    AssistantState.THINKING: 3.0,
    AssistantState.RESPONDING: 5.0,
}
GLOW_ALPHA = {
    AssistantState.IDLE: 40,
    AssistantState.THINKING: 90,
    AssistantState.RESPONDING: 110,
}


class AssistantOrb(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = AssistantState.IDLE
        self._angle = 0.0  # degrees
        self._pulse = 0.0  # radians
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_INTERVAL_MS[self._state])
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(120, 120)

    @property
    def state(self) -> AssistantState:
        return self._state

    def set_state(self, state: AssistantState) -> None:
        self._state = state
        self._timer.setInterval(FRAME_INTERVAL_MS[state])
        self.update()

    # -- animation clock ---------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._last_tick = time.monotonic()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()  # nothing to animate when nobody can see it
        super().hideEvent(event)

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = min(now - self._last_tick, 0.25)  # a long pause must not cause a jump
        self._last_tick = now
        self._angle = (self._angle + elapsed * ROTATION_DEG_PER_S[self._state]) % 360.0
        self._pulse = (self._pulse + elapsed * PULSE_RAD_PER_S[self._state]) % (2 * math.pi)
        self.update()

    # -- drawing -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 200, side / 200)  # draw in a fixed 200 x 200 space

        cyan = QColor(COLORS["cyan"])
        blue = QColor(COLORS["blue"])
        pulse = (math.sin(self._pulse) + 1) / 2  # 0..1
        glow = GLOW_ALPHA[self._state] + int(pulse * 40)

        # soft glow behind everything
        gradient = QRadialGradient(QPointF(0, 0), 95)
        gradient.setColorAt(0.0, QColor(cyan.red(), cyan.green(), cyan.blue(), glow))
        gradient.setColorAt(0.6, QColor(blue.red(), blue.green(), blue.blue(), glow // 3))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0, 0), 95, 95)

        # thin outer ring
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(cyan.red(), cyan.green(), cyan.blue(), 110), 1.5))
        painter.drawEllipse(QPointF(0, 0), 88, 88)

        # dashed ring, slowly turning
        painter.save()
        painter.rotate(self._angle)
        dashed = QPen(QColor(blue.red(), blue.green(), blue.blue(), 170), 2)
        dashed.setDashPattern([2.0, 5.0])
        painter.setPen(dashed)
        painter.drawEllipse(QPointF(0, 0), 74, 74)
        painter.restore()

        # three bright arcs, turning the other way
        painter.save()
        painter.rotate(-self._angle * 1.6)
        painter.setPen(QPen(cyan, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        arc_box = QRectF(-58, -58, 116, 116)
        for k in range(3):
            painter.drawArc(arc_box, int(k * 120 * 16), int(60 * 16))  # Qt angles are in 1/16 degree
        painter.restore()

        # glowing core that breathes
        radius = 20 + pulse * (6 if self._state is not AssistantState.IDLE else 2)
        core = QRadialGradient(QPointF(0, 0), radius)
        core.setColorAt(0.0, QColor(255, 255, 255, 235))
        core.setColorAt(0.45, cyan)
        core.setColorAt(1.0, QColor(blue.red(), blue.green(), blue.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
