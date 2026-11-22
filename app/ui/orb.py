"""Sky's animated "eye": a cat-eye inspired assistant visualization.

How the eye shows what Sky is doing:
  * READY       a relaxed, half-lidded eye with a narrow slit pupil. It blinks now and then.
  * THINKING    wide open, the pupil dilates, and a scanning ring sweeps around it.
  * RESPONDING  alert, the pupil narrows to a medium slit and the glow pulses.

It is drawn with QPainter, so it needs no image files, and it is deliberately
cheap to run:
  * it animates at ~12 frames per second while idle and ~30 while something moves,
  * it stops completely while the window is hidden or minimized.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from app.core.events import AssistantState
from app.ui.theme import COLORS

SLOW_FRAME_MS = 80  # calm: nothing is moving quickly
FAST_FRAME_MS = 33  # busy, blinking, or changing shape

FRAME_INTERVAL_MS = {
    AssistantState.IDLE: SLOW_FRAME_MS,
    AssistantState.THINKING: FAST_FRAME_MS,
    AssistantState.RESPONDING: FAST_FRAME_MS,
}
ROTATION_DEG_PER_S = {
    AssistantState.IDLE: 6.0,
    AssistantState.THINKING: 140.0,
    AssistantState.RESPONDING: 50.0,
}
PULSE_RAD_PER_S = {
    AssistantState.IDLE: 1.2,
    AssistantState.THINKING: 3.0,
    AssistantState.RESPONDING: 5.0,
}
GLOW_ALPHA = {
    AssistantState.IDLE: 45,
    AssistantState.THINKING: 95,
    AssistantState.RESPONDING: 120,
}
# Half-width of the pupil, in the 200 x 200 drawing space. Small = a thin slit.
PUPIL_HALF_WIDTH = {
    AssistantState.IDLE: 6.0,
    AssistantState.THINKING: 26.0,
    AssistantState.RESPONDING: 12.0,
}
# How open the eyelids are: 1.0 = fully open.
EYE_OPENNESS = {
    AssistantState.IDLE: 0.80,
    AssistantState.THINKING: 1.0,
    AssistantState.RESPONDING: 0.90,
}
BLINK_SECONDS = 0.24
BLINK_INTERVAL_S = (3.0, 7.0)  # a random wait between blinks while idle

EYE_HALF_WIDTH = 78.0
EYE_FULL_HALF_HEIGHT = 58.0
PUPIL_HALF_HEIGHT = 64.0  # taller than the eye, so the slit always reaches both eyelids


def _with_alpha(color: QColor, alpha: int) -> QColor:
    return QColor(color.red(), color.green(), color.blue(), alpha)


class AssistantOrb(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = AssistantState.IDLE
        self._angle = 0.0  # degrees, for the rotating rings
        self._pulse = 0.0  # radians, for the breathing glow
        self._pupil = PUPIL_HALF_WIDTH[self._state]
        self._openness = EYE_OPENNESS[self._state]
        self._blink_amount = 0.0  # 0 = open, 1 = fully closed
        self._blink_start: float | None = None
        self._rng = random.Random()
        self._last_tick = time.monotonic()
        self._next_blink = self._last_tick + self._rng.uniform(*BLINK_INTERVAL_S)
        self._streaks = self._make_streaks()

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_INTERVAL_MS[self._state])
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(120, 120)

    # -- public API --------------------------------------------------------
    @property
    def state(self) -> AssistantState:
        return self._state

    @property
    def pupil_half_width(self) -> float:
        return self._pupil

    @property
    def eye_openness(self) -> float:
        """How open the eye is right now, including a blink in progress."""
        return self._openness * (1.0 - 0.96 * self._blink_amount)

    def set_state(self, state: AssistantState) -> None:
        self._state = state
        self._timer.setInterval(FAST_FRAME_MS)  # the eye is about to change shape; _tick slows down again
        self.update()

    def blink(self) -> None:
        """Blink once, right now."""
        self._blink_start = time.monotonic()
        self._timer.setInterval(FAST_FRAME_MS)

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
        state = self._state

        self._angle = (self._angle + elapsed * ROTATION_DEG_PER_S[state]) % 360.0
        self._pulse = (self._pulse + elapsed * PULSE_RAD_PER_S[state]) % (2 * math.pi)

        # blinking: only while relaxed, and never while Sky is concentrating
        if state is AssistantState.IDLE and self._blink_start is None and now >= self._next_blink:
            self._blink_start = now
        self._blink_amount = 0.0
        if self._blink_start is not None:
            progress = (now - self._blink_start) / BLINK_SECONDS
            if progress >= 1.0:
                self._blink_start = None
                self._next_blink = now + self._rng.uniform(*BLINK_INTERVAL_S)
            else:
                self._blink_amount = math.sin(math.pi * progress)  # closes, then opens again

        # ease the pupil and eyelids toward the current mood instead of jumping
        ease = min(1.0, elapsed * 9.0)
        pupil_target, open_target = PUPIL_HALF_WIDTH[state], EYE_OPENNESS[state]
        self._pupil += (pupil_target - self._pupil) * ease
        self._openness += (open_target - self._openness) * ease

        settling = abs(self._pupil - pupil_target) > 0.3 or abs(self._openness - open_target) > 0.01
        busy = settling or self._blink_start is not None
        interval = FAST_FRAME_MS if busy else FRAME_INTERVAL_MS[state]
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        self.update()

    # -- drawing -----------------------------------------------------------
    @staticmethod
    def _make_streaks() -> list[tuple[float, float, float, int]]:
        """Fine lines radiating from the pupil, like the fibres of a real iris."""
        rng = random.Random(7)  # fixed seed: the same iris every time
        streaks = []
        for k in range(48):
            angle = math.radians(k * 7.5 + rng.uniform(-2, 2))
            inner = rng.uniform(14, 26)
            outer = rng.uniform(48, 74)
            streaks.append((angle, inner, outer, rng.randint(22, 55)))
        return streaks

    @staticmethod
    def _eye_path(openness: float) -> QPainterPath:
        """An almond shape, pointed at both corners. ``openness`` scales its height."""
        half_height = EYE_FULL_HALF_HEIGHT * max(openness, 0.02)
        path = QPainterPath()
        path.moveTo(-EYE_HALF_WIDTH, 0)
        # a quadratic curve peaks at half the distance to its control point
        path.quadTo(0, -2 * half_height, EYE_HALF_WIDTH, 0)
        path.quadTo(0, 2 * half_height, -EYE_HALF_WIDTH, 0)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(side / 200, side / 200)  # draw in a fixed 200 x 200 space

        accent = QColor(COLORS["accent"])
        deep = QColor(COLORS["accent2"])
        pulse = (math.sin(self._pulse) + 1) / 2  # 0..1
        glow = GLOW_ALPHA[self._state] + int(pulse * 45)

        # soft glow behind everything
        gradient = QRadialGradient(QPointF(0, 0), 98)
        gradient.setColorAt(0.0, _with_alpha(accent, glow))
        gradient.setColorAt(0.6, _with_alpha(deep, glow // 3))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0, 0), 98, 98)

        # HUD rings around the eye
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(accent, 90), 1.2))
        painter.drawEllipse(QPointF(0, 0), 94, 94)

        painter.save()
        painter.rotate(self._angle)
        dashed = QPen(_with_alpha(deep, 190), 2)
        dashed.setDashPattern([2.0, 6.0])
        painter.setPen(dashed)
        painter.drawEllipse(QPointF(0, 0), 86, 86)
        painter.restore()

        if self._state is AssistantState.THINKING:  # the scanning sweep
            painter.save()
            painter.rotate(-self._angle * 1.3)
            painter.setPen(QPen(accent, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            ring = QRectF(-86, -86, 172, 172)
            for k in range(2):
                painter.drawArc(ring, int(k * 180 * 16), int(45 * 16))  # Qt angles are in 1/16 degree
            painter.restore()

        # the eye itself
        eye = self._eye_path(self.eye_openness)
        painter.save()
        painter.setClipPath(eye)

        iris = QRadialGradient(QPointF(0, 0), 80)
        iris.setColorAt(0.0, QColor("#FF8A5B"))
        iris.setColorAt(0.35, accent)
        iris.setColorAt(0.78, deep)
        iris.setColorAt(1.0, QColor("#3B0610"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(iris)
        painter.drawRect(QRectF(-EYE_HALF_WIDTH - 2, -66, 2 * EYE_HALF_WIDTH + 4, 132))

        for angle, inner, outer, alpha in self._streaks:
            painter.setPen(QPen(QColor(255, 214, 200, alpha), 0.9))
            painter.drawLine(
                QPointF(math.cos(angle) * inner, math.sin(angle) * inner),
                QPointF(math.cos(angle) * outer, math.sin(angle) * outer),
            )

        painter.setPen(QPen(_with_alpha(accent, 150), 1.6))
        painter.setBrush(QColor("#0A0205"))
        painter.drawEllipse(QPointF(0, 0), self._pupil, PUPIL_HALF_HEIGHT)  # the slit pupil

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 200))
        painter.drawEllipse(QPointF(-(self._pupil * 0.45 + 3), -20), 3.6, 6.0)  # a glint of light
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_with_alpha(accent, 230), 2.6))
        painter.drawPath(eye)  # the eyelid outline