"""Tests for the bridge, the main window and the application wiring (headless, fake model)."""
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Qt, Slot  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app.ai.model_manager import Check, HealthReport, Severity  # noqa: E402
from app.ai.ollama_client import ChatChunk, ChatStats, OllamaUnavailableError  # noqa: E402
from app.core.config import SkyConfig  # noqa: E402
from app.core.event_manager import EventManager  # noqa: E402
from app.core.events import AnswerToken, AssistantState, ConversationReset, StateChanged  # noqa: E402
from app.ui.app import create_gui  # noqa: E402
from app.ui.qt_bridge import QtEventBridge  # noqa: E402
from app.utils.system_info import SystemInfo  # noqa: E402

WAIT = 5


class FakeBackend:
    """Scripted language model. ``gate_after=n`` pauses after token n so tests can act mid-answer."""

    def __init__(self, tokens=("Hello", " world"), error=None, gate_after=None):
        self.tokens = list(tokens)
        self.error = error
        self.gate_after = gate_after
        self.reached_gate = threading.Event()
        self.gate = threading.Event()
        self.calls = []

    def chat_stream(self, messages, *, model, num_ctx, temperature, keep_alive, think=None, cancel=None):
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        for index, text in enumerate(self.tokens):
            if cancel is not None and cancel.is_set():
                return
            yield ChatChunk(text=text)
            if self.gate_after == index:
                self.reached_gate.set()
                assert self.gate.wait(WAIT), "test forgot to open the gate"
        if cancel is not None and cancel.is_set():
            return
        yield ChatChunk(
            done=True,
            done_reason="stop",
            stats=ChatStats(output_tokens=2, output_s=0.2, prompt_tokens=30, prompt_s=0.5),
        )


def make_system(ram=8.0, disk=50.0):
    return SystemInfo("TestOS", "3.13.5", 4, 8, 16.0, ram, "C:/", disk)


@pytest.fixture
def make_gui(qapp):
    """Build a GUI around a fake backend; everything is cleaned up after the test."""
    created = []

    def factory(backend=None):
        backend = backend or FakeBackend()
        parts = create_gui(SkyConfig(), backend=backend)
        parts.window.show()
        created.append((parts, backend))
        return parts, backend

    yield factory

    for parts, backend in created:
        backend.gate.set()  # never leave a worker thread waiting
        parts.window.close()
        parts.close()
        parts.window.deleteLater()


def ask(parts, pump, text="Hi"):
    parts.window.input.setText(text)
    QTest.mouseClick(parts.window.send_button, Qt.MouseButton.LeftButton)
    assert pump(lambda: parts.assistant.state is AssistantState.IDLE and text in parts.window.chat.plain_text())
    assert parts.assistant.wait_until_idle(WAIT)
    qapp_events = parts.app
    qapp_events.processEvents()


# --------------------------------------------------------------------- bridge
class Receiver(QObject):
    """A QObject with slots, like a window: Qt delivers queued signals on its thread."""

    def __init__(self):
        super().__init__()
        self.tokens = []
        self.threads = []

    @Slot(str)
    def on_token(self, text):
        self.tokens.append(text)
        self.threads.append(threading.current_thread())


def test_bridge_delivers_events_on_the_ui_thread(qapp, pump):
    events = EventManager()
    bridge = QtEventBridge(events)
    receiver = Receiver()
    bridge.token.connect(receiver.on_token)

    worker = threading.Thread(target=lambda: events.publish(AnswerToken("from worker")))
    worker.start()
    worker.join()

    assert pump(lambda: receiver.tokens == ["from worker"])
    assert receiver.threads == [threading.main_thread()]  # not the worker thread
    bridge.disconnect_events()


def test_bridge_stops_delivering_after_disconnect(qapp, pump):
    events = EventManager()
    bridge = QtEventBridge(events)
    receiver = Receiver()
    bridge.token.connect(receiver.on_token)

    bridge.disconnect_events()
    events.publish(AnswerToken("ignored"))
    pump(lambda: False, timeout=0.1)

    assert receiver.tokens == []


# --------------------------------------------------------------------- window
def test_window_starts_ready(make_gui):
    parts, _ = make_gui()
    window = parts.window

    assert window.state_label.text() == "READY"
    assert window.send_button.isEnabled() and not window.stop_button.isEnabled()
    assert "llama3.2:3b" in window.chat.plain_text()  # the "online" notice names the model


def test_sending_a_message_shows_the_conversation(make_gui, pump):
    parts, backend = make_gui()
    ask(parts, pump, "Hi")
    window = parts.window

    text = window.chat.plain_text()
    assert "YOU" in text and "Hi" in text and "Hello world" in text
    assert window.input.text() == ""  # the box is cleared after sending
    assert window.send_button.isEnabled() and not window.stop_button.isEnabled()
    assert "tok/s" in window.status_label.text()
    assert len(backend.calls) == 1


def test_enter_key_sends_the_message(make_gui, pump):
    parts, backend = make_gui()
    parts.window.input.setText("Via enter")

    QTest.keyClick(parts.window.input, Qt.Key.Key_Return)

    assert pump(lambda: "Hello world" in parts.window.chat.plain_text())
    assert backend.calls[0][-1].content == "Via enter"


def test_blank_input_sends_nothing(make_gui, pump):
    parts, backend = make_gui()
    parts.window.input.setText("    ")

    QTest.mouseClick(parts.window.send_button, Qt.MouseButton.LeftButton)
    pump(lambda: False, timeout=0.1)

    assert backend.calls == []


def test_controls_reflect_a_busy_assistant_and_keep_unsent_text(make_gui, pump):
    parts, backend = make_gui(FakeBackend(gate_after=0))
    window = parts.window

    window.input.setText("first")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert backend.reached_gate.wait(WAIT)
    assert pump(lambda: window.state_label.text() == "RESPONDING")

    assert not window.send_button.isEnabled() and window.stop_button.isEnabled()
    assert window.orb.state is AssistantState.RESPONDING

    window.input.setText("second")
    window.submit_text()  # pressing Enter while busy
    assert window.input.text() == "second"  # not lost, not sent
    assert len(backend.calls) == 1

    backend.gate.set()
    assert pump(lambda: window.state_label.text() == "READY")
    assert window.send_button.isEnabled() and not window.stop_button.isEnabled()


def test_stop_button_stops_the_answer_and_says_so(make_gui, pump):
    parts, backend = make_gui(FakeBackend(tokens=("One", " two", " three"), gate_after=0))
    window = parts.window
    window.input.setText("count")
    QTest.mouseClick(window.send_button, Qt.MouseButton.LeftButton)
    assert backend.reached_gate.wait(WAIT)
    assert pump(lambda: window.stop_button.isEnabled())  # let the window catch up, as a real user would

    QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    backend.gate.set()

    assert pump(lambda: "Stopped." in window.chat.plain_text())
    assert "One" in window.chat.plain_text()
    assert "three" not in window.chat.plain_text()
    assert pump(lambda: window.send_button.isEnabled())


def test_escape_key_also_stops_the_answer(make_gui, pump):
    parts, backend = make_gui(FakeBackend(tokens=("One", " two"), gate_after=0))
    window = parts.window
    window.input.setText("count")
    window.submit_text()
    assert backend.reached_gate.wait(WAIT)
    assert pump(lambda: window.stop_button.isEnabled())  # keys only reach a window that has caught up

    QTest.keyClick(window, Qt.Key.Key_Escape)
    backend.gate.set()

    assert pump(lambda: "Stopped." in window.chat.plain_text())


def test_an_error_is_shown_as_a_friendly_message(make_gui, pump):
    parts, _ = make_gui(FakeBackend(error=OllamaUnavailableError("connection refused")))
    window = parts.window
    window.input.setText("Hi")
    window.submit_text()

    assert pump(lambda: "Ollama is running" in window.chat.plain_text())
    assert pump(lambda: window.send_button.isEnabled())
    assert "could not be answered" in window.status_label.text()


def test_new_button_clears_the_transcript_and_the_memory(make_gui, pump):
    parts, backend = make_gui()
    ask(parts, pump, "remember me")
    window = parts.window

    QTest.mouseClick(window.new_button, Qt.MouseButton.LeftButton)
    assert pump(lambda: "New conversation." in window.chat.plain_text())
    assert "remember me" not in window.chat.plain_text()

    ask(parts, pump, "who am I?")
    assert [m.role for m in backend.calls[1]] == ["system", "user"]  # no history was sent


def test_health_report_problems_are_shown(make_gui, pump):
    parts, _ = make_gui()
    window = parts.window
    report = HealthReport(
        checks=(
            Check("ollama", Severity.ERROR, "Ollama is not responding at http://127.0.0.1:11434."),
            Check("memory", Severity.WARNING, "Only 1.0 GB RAM is available."),
            Check("disk", Severity.OK, "26.2 GB free disk space"),
        ),
        system=make_system(),
    )

    window.request_health_check(lambda: report)  # runs on a background thread

    assert pump(lambda: window.health_report is report)
    text = window.chat.plain_text()
    assert "not responding" in text and "Only 1.0 GB RAM" in text
    assert "26.2 GB" not in text  # healthy checks stay quiet
    assert "Not ready" in window.status_label.text()


def test_a_healthy_report_adds_no_noise(make_gui, pump):
    parts, _ = make_gui()
    window = parts.window
    before = window.chat.plain_text()
    report = HealthReport(checks=(Check("ollama", Severity.OK, "Ollama 0.40.11 is running"),), system=make_system())

    window.request_health_check(lambda: report)

    assert pump(lambda: window.health_report is report)
    assert window.chat.plain_text() == before
    assert window.status_label.text() == "Ready"


def test_a_crashing_health_check_does_not_break_the_window(make_gui, pump):
    parts, _ = make_gui()

    def broken():
        raise RuntimeError("health check bug")

    parts.window.request_health_check(broken)
    pump(lambda: False, timeout=0.2)

    assert parts.window.health_report is None
    assert parts.window.send_button.isEnabled()


def test_closing_the_window_stops_a_running_answer(make_gui, pump):
    parts, backend = make_gui(FakeBackend(tokens=("a", "b", "c"), gate_after=0))
    parts.window.input.setText("hi")
    parts.window.submit_text()
    assert backend.reached_gate.wait(WAIT)

    threading.Timer(0.1, backend.gate.set).start()
    parts.window.close()

    assert parts.assistant.state is AssistantState.IDLE


def test_events_after_close_do_not_reach_the_dead_window(make_gui, pump):
    parts, _ = make_gui()
    parts.window.close()

    parts.events.publish(AnswerToken("late"))  # must not raise
    parts.events.publish(StateChanged(AssistantState.THINKING))
    parts.events.publish(ConversationReset())
    pump(lambda: False, timeout=0.1)

    assert "late" not in parts.window.chat.plain_text()
