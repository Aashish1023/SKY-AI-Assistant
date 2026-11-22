"""Tests for the theme, the orb and the transcript view."""
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

from app.core.events import AssistantState  # noqa: E402
from app.ui.chat_view import ChatView  # noqa: E402
from app.ui.orb import BLINK_SECONDS, EYE_OPENNESS, FRAME_INTERVAL_MS, PUPIL_HALF_WIDTH, AssistantOrb  # noqa: E402
from app.ui.theme import COLORS, build_stylesheet  # noqa: E402


# ---------------------------------------------------------------------- theme
def test_stylesheet_uses_the_palette():
    css = build_stylesheet()

    assert COLORS["accent"] in css and COLORS["bg"] in css
    assert css.count("{") == css.count("}")


def _rgb(hex_color):
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))


@pytest.mark.parametrize("key", ["accent", "accent_hover", "accent2", "accent_dim", "border", "user", "text"])
def test_palette_is_red_not_blue(key):
    red, _green, blue = _rgb(COLORS[key])

    assert red > blue, f"{key} ({COLORS[key]}) should lean red, not blue"


def test_errors_are_distinguishable_from_the_red_accent():
    assert COLORS["error"] != COLORS["accent"]
    assert _rgb(COLORS["error"])[1] > _rgb(COLORS["accent"])[1] + 50  # more green: orange, not red


def test_stylesheet_is_accepted_by_qt_without_warnings(qapp):
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, text: messages.append((kind, text)))
    try:
        widget = QWidget()
        widget.setStyleSheet(build_stylesheet())
        widget.show()
        qapp.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)

    problems = [text for kind, text in messages if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg)]
    assert problems == []


# ------------------------------------------------------------------------ orb
def test_orb_animates_faster_when_working_than_when_idle(qapp):
    orb = AssistantOrb()

    assert orb.state is AssistantState.IDLE
    idle_interval = orb._timer.interval()
    orb.set_state(AssistantState.THINKING)

    assert orb.state is AssistantState.THINKING
    assert orb._timer.interval() == FRAME_INTERVAL_MS[AssistantState.THINKING] < idle_interval


def test_orb_stops_its_timer_while_hidden(qapp):
    orb = AssistantOrb()
    assert not orb._timer.isActive()  # not shown yet, so not running

    orb.show()
    assert orb._timer.isActive()

    orb.hide()
    assert not orb._timer.isActive()  # a hidden or minimized window costs nothing


def test_orb_rotation_advances_with_time(qapp):
    orb = AssistantOrb()
    orb.set_state(AssistantState.THINKING)
    orb._last_tick -= 0.1  # pretend 100 ms have passed

    orb._tick()

    assert orb._angle > 0


def test_orb_draws_something_for_every_state(qapp):
    orb = AssistantOrb()
    orb.resize(160, 160)

    for state in AssistantState:
        orb.set_state(state)
        image = orb.grab().toImage()
        assert image.pixelColor(80, 80).alpha() > 0  # the glowing core is painted at the centre


def test_pupil_dilates_when_thinking_and_narrows_again_when_idle(qapp):
    orb = AssistantOrb()
    assert orb.pupil_half_width == PUPIL_HALF_WIDTH[AssistantState.IDLE]

    orb.set_state(AssistantState.THINKING)
    for _ in range(40):
        orb._last_tick -= 0.05
        orb._tick()
    assert orb.pupil_half_width == pytest.approx(PUPIL_HALF_WIDTH[AssistantState.THINKING], abs=1.0)

    orb.set_state(AssistantState.IDLE)
    for _ in range(40):
        orb._last_tick -= 0.05
        orb._tick()
    assert orb.pupil_half_width == pytest.approx(PUPIL_HALF_WIDTH[AssistantState.IDLE], abs=1.0)


def test_pupil_changes_smoothly_not_in_one_jump(qapp):
    orb = AssistantOrb()
    orb.set_state(AssistantState.THINKING)
    orb._last_tick -= 0.033

    orb._tick()  # a single frame

    idle, thinking = PUPIL_HALF_WIDTH[AssistantState.IDLE], PUPIL_HALF_WIDTH[AssistantState.THINKING]
    assert idle < orb.pupil_half_width < thinking


def test_eye_is_more_open_when_alert_than_when_relaxed(qapp):
    assert EYE_OPENNESS[AssistantState.THINKING] > EYE_OPENNESS[AssistantState.IDLE]


def test_a_blink_closes_the_eye_and_then_opens_it_again(qapp):
    orb = AssistantOrb()
    resting = orb.eye_openness

    orb.blink()
    orb._blink_start = time.monotonic() - BLINK_SECONDS / 2  # halfway through the blink
    orb._tick()
    assert orb.eye_openness < resting * 0.2  # nearly shut

    orb._blink_start = time.monotonic() - BLINK_SECONDS * 2  # long finished
    orb._tick()
    assert orb._blink_start is None
    assert orb.eye_openness == pytest.approx(resting, abs=0.02)


def test_idle_eye_blinks_by_itself_after_a_while(qapp):
    orb = AssistantOrb()
    orb._next_blink = time.monotonic() - 1  # a blink is overdue

    orb._tick()

    assert orb._blink_start is not None


def test_no_blinking_while_concentrating(qapp):
    orb = AssistantOrb()
    orb.set_state(AssistantState.THINKING)
    orb._next_blink = time.monotonic() - 1

    orb._tick()

    assert orb._blink_start is None


def test_timer_slows_down_again_once_the_eye_has_settled(qapp):
    orb = AssistantOrb()
    orb.set_state(AssistantState.THINKING)
    orb.set_state(AssistantState.IDLE)
    assert orb._timer.interval() == FRAME_INTERVAL_MS[AssistantState.THINKING]  # still moving: fast frames

    for _ in range(60):
        orb._last_tick -= 0.05
        orb._tick()
        orb._next_blink = time.monotonic() + 100  # keep this test about the pupil, not blinking

    assert orb._timer.interval() == FRAME_INTERVAL_MS[AssistantState.IDLE]  # settled: back to slow frames


def test_the_iris_is_painted_red(qapp):
    orb = AssistantOrb()
    orb.resize(160, 160)
    image = orb.grab().toImage()

    colour = image.pixelColor(80 + 32, 80)  # a point on the iris, right of the pupil

    assert colour.red() > colour.blue() + 40


# ------------------------------------------------------------------ chat view
def test_transcript_shows_speakers_and_streamed_text_in_order(qapp):
    view = ChatView()
    view.add_user_message("Hi there")
    for piece in ("Hel", "lo", "!"):
        view.append_sky_text(piece)
    view.end_sky_message()

    text = view.plain_text()
    assert text.index("YOU") < text.index("Hi there") < text.index("SKY") < text.index("Hello!")
    assert text.count("SKY") == 1  # streaming pieces join one message, not many


def test_speaker_label_names_can_be_customised(qapp):
    view = ChatView()
    view.append_sky_text("Hi", label="NOVA")

    assert "NOVA" in view.plain_text()


def test_notice_closes_an_open_message_and_a_new_one_gets_its_own_label(qapp):
    view = ChatView()
    view.append_sky_text("First answer")
    view.add_notice("Stopped.")
    view.append_sky_text("Second answer")

    text = view.plain_text()
    assert text.count("SKY") == 2
    assert text.index("First answer") < text.index("Stopped.") < text.index("Second answer")


def test_clear_empties_the_transcript(qapp):
    view = ChatView()
    view.append_sky_text("Old")
    view.clear_transcript()
    view.append_sky_text("New")

    text = view.plain_text()
    assert "Old" not in text
    assert text.count("SKY") == 1


def test_view_follows_new_text_only_when_already_at_the_bottom(qapp, pump):
    view = ChatView()
    view.resize(320, 160)
    view.show()
    for i in range(60):
        view.add_user_message(f"message {i}")
    pump(lambda: view.verticalScrollBar().maximum() > 0)
    bar = view.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.value() == bar.maximum()  # followed the text while at the bottom

    bar.setValue(0)  # the user scrolls up to re-read something
    view.add_notice("a new line arrives")
    qapp.processEvents()
    assert bar.value() == 0  # and is not dragged away

    bar.setValue(bar.maximum())  # back at the bottom: following resumes
    view.add_notice("another line")
    qapp.processEvents()
    assert bar.value() == bar.maximum()
    view.close()