"""Tests for app.core.assistant, using a scripted fake model (no Ollama needed).

The fake can pause at a "gate", so threaded behaviour is tested deterministically
instead of with sleeps.
"""
import threading

import pytest

from app.ai.ollama_client import (
    ChatChunk,
    ChatStats,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaUnavailableError,
)
from app.core.assistant import Assistant
from app.core.config import SkyConfig
from app.core.event_manager import EventManager
from app.core.events import (
    AnswerFailed,
    AnswerFinished,
    AnswerToken,
    AssistantState,
    ConversationReset,
    Event,
    StateChanged,
    UserMessageSubmitted,
)

WAIT = 5  # seconds; only reached if a test is about to fail


class FakeBackend:
    """Streams scripted tokens. ``gate_after=n`` pauses after token n (-1 = before the first)."""

    def __init__(self, tokens=("Hello", " world"), error=None, gate_after=None):
        self.tokens = list(tokens)
        self.error = error
        self.gate_after = gate_after
        self.reached_gate = threading.Event()
        self.gate = threading.Event()
        self.calls = []
        self.last_stream_closed = False

    def chat_stream(self, messages, *, model, num_ctx, temperature, keep_alive, think=None, cancel=None):
        self.calls.append(
            {"messages": list(messages), "model": model, "num_ctx": num_ctx,
             "temperature": temperature, "keep_alive": keep_alive, "cancel": cancel}
        )
        try:
            if self.error is not None:
                raise self.error
            if self.gate_after == -1:
                self._pause()
            for index, text in enumerate(self.tokens):
                if cancel is not None and cancel.is_set():
                    return
                yield ChatChunk(text=text)
                if self.gate_after == index:
                    self._pause()
            if cancel is not None and cancel.is_set():
                return
            yield ChatChunk(done=True, done_reason="stop",
                            stats=ChatStats(output_tokens=len(self.tokens), output_s=1.0))
        finally:
            self.last_stream_closed = True

    def _pause(self):
        self.reached_gate.set()
        assert self.gate.wait(WAIT), "test forgot to open the gate"


class Recorder:
    def __init__(self, events):
        self.events = []
        events.subscribe(Event, self.events.append)

    def of(self, kind):
        return [e for e in self.events if isinstance(e, kind)]

    def kinds(self):
        return [type(e).__name__ for e in self.events]


@pytest.fixture
def events():
    return EventManager()


@pytest.fixture
def recorder(events):
    return Recorder(events)


def make(events, backend):
    return Assistant(SkyConfig(), backend, events)


def ask(assistant, text):
    assert assistant.submit(text)
    assert assistant.wait_until_idle(WAIT)


# ------------------------------------------------------------------- happy path
def test_answer_publishes_events_in_order(events, recorder):
    assistant = make(events, FakeBackend())
    ask(assistant, "Hi")

    assert recorder.kinds() == [
        "UserMessageSubmitted", "StateChanged", "StateChanged",
        "AnswerToken", "AnswerToken", "AnswerFinished", "StateChanged",
    ]
    assert [e.state for e in recorder.of(StateChanged)] == [
        AssistantState.THINKING, AssistantState.RESPONDING, AssistantState.IDLE,
    ]
    assert recorder.of(UserMessageSubmitted)[0].text == "Hi"
    finished = recorder.of(AnswerFinished)[0]
    assert finished.text == "Hello world"
    assert finished.cancelled is False
    assert finished.done_reason == "stop"
    assert finished.stats.output_tokens == 2
    assert assistant.state is AssistantState.IDLE


def test_settings_are_passed_to_the_backend(events):
    backend = FakeBackend()
    ask(make(events, backend), "Hi")

    call = backend.calls[0]
    assert call["model"] == "llama3.2:3b"
    assert call["num_ctx"] == 4096
    assert call["temperature"] == 0.7
    assert call["keep_alive"] == "10m"
    assert isinstance(call["cancel"], threading.Event)
    assert backend.last_stream_closed


def test_the_conversation_is_remembered(events):
    backend = FakeBackend(tokens=("Nice to meet you, Andy.",))
    assistant = make(events, backend)

    ask(assistant, "My name is Andy")
    ask(assistant, "What is my name?")

    second = backend.calls[1]["messages"]
    assert [m.role for m in second] == ["system", "user", "assistant", "user"]
    assert second[1].content == "My name is Andy"
    assert second[2].content == "Nice to meet you, Andy."


def test_blank_messages_are_ignored(events, recorder):
    assistant = make(events, FakeBackend())

    assert assistant.submit("   ") is False
    assert recorder.events == []


# ------------------------------------------------------------- one at a time
def test_a_second_question_while_busy_is_refused(events):
    backend = FakeBackend(gate_after=0)
    assistant = make(events, backend)

    assert assistant.submit("first")
    assert backend.reached_gate.wait(WAIT)

    assert assistant.state is AssistantState.RESPONDING
    assert assistant.submit("second") is False
    assert len(backend.calls) == 1

    backend.gate.set()
    assert assistant.wait_until_idle(WAIT)
    assert assistant.submit("third")  # works again afterwards
    assert assistant.wait_until_idle(WAIT)


# -------------------------------------------------------------- cancelling
def test_cancel_keeps_the_partial_answer(events, recorder):
    backend = FakeBackend(tokens=("One", " two", " three"), gate_after=0)
    assistant = make(events, backend)

    assert assistant.submit("count")
    assert backend.reached_gate.wait(WAIT)
    assistant.cancel()
    backend.gate.set()
    assert assistant.wait_until_idle(WAIT)

    finished = recorder.of(AnswerFinished)[0]
    assert finished.cancelled is True
    assert finished.text == "One"

    follow_up = FakeBackend()
    assistant._backend = follow_up
    ask(assistant, "next")
    history = follow_up.calls[0]["messages"]
    assert [m.content for m in history[1:3]] == ["count", "One"]  # partial answer was remembered


def test_cancel_before_any_text_remembers_nothing(events, recorder):
    backend = FakeBackend(gate_after=-1)
    assistant = make(events, backend)

    assert assistant.submit("hello?")
    assert backend.reached_gate.wait(WAIT)
    assistant.cancel()
    backend.gate.set()
    assert assistant.wait_until_idle(WAIT)

    finished = recorder.of(AnswerFinished)[0]
    assert finished.cancelled is True and finished.text == ""
    assert assistant._prompts.turn_count == 0


def test_cancel_after_the_answer_finished_is_not_reported_as_cancelled(events, recorder):
    assistant = make(events, FakeBackend())
    ask(assistant, "Hi")
    assistant.cancel()  # too late: nothing is running

    assert recorder.of(AnswerFinished)[0].cancelled is False


def test_shutdown_cancels_and_waits(events):
    backend = FakeBackend(gate_after=0)
    assistant = make(events, backend)
    assert assistant.submit("hi")
    assert backend.reached_gate.wait(WAIT)

    threading.Timer(0.1, backend.gate.set).start()  # release the fake shortly after shutdown begins
    assistant.shutdown(timeout=WAIT)

    assert assistant.state is AssistantState.IDLE


# ----------------------------------------------------------------- failures
def test_unreachable_model_gives_a_friendly_message(events, recorder):
    assistant = make(events, FakeBackend(error=OllamaUnavailableError("connection refused")))
    ask(assistant, "Hi")

    failed = recorder.of(AnswerFailed)[0]
    assert "Ollama is running" in failed.message
    assert "connection refused" in failed.details
    assert recorder.of(AnswerFinished) == []
    assert assistant.state is AssistantState.IDLE


def test_missing_model_message_includes_the_pull_command(events, recorder):
    assistant = make(events, FakeBackend(error=OllamaModelNotFoundError("model not found")))
    ask(assistant, "Hi")

    assert "ollama pull llama3.2:3b" in recorder.of(AnswerFailed)[0].message


def test_other_ollama_errors_are_reported(events, recorder):
    assistant = make(events, FakeBackend(error=OllamaResponseError("bad json")))
    ask(assistant, "Hi")

    assert "could not understand" in recorder.of(AnswerFailed)[0].message


def test_unexpected_bug_is_reported_and_sky_keeps_working(events, recorder):
    backend = FakeBackend(error=RuntimeError("bug"))
    assistant = make(events, backend)
    ask(assistant, "Hi")

    assert "Something went wrong" in recorder.of(AnswerFailed)[0].message
    assert assistant.state is AssistantState.IDLE

    backend.error = None
    ask(assistant, "Try again")
    assert recorder.of(AnswerFinished)[0].text == "Hello world"


def test_a_failed_question_is_not_remembered(events):
    backend = FakeBackend(error=OllamaUnavailableError("down"))
    assistant = make(events, backend)
    ask(assistant, "This fails")

    backend.error = None
    ask(assistant, "This works")

    messages = backend.calls[1]["messages"]
    assert [m.role for m in messages] == ["system", "user"]
    assert messages[1].content == "This works"


# --------------------------------------------------------------------- reset
def test_reset_clears_history_and_announces_it(events, recorder):
    backend = FakeBackend()
    assistant = make(events, backend)
    ask(assistant, "remember this")

    assistant.reset()
    ask(assistant, "who am I?")

    assert len(recorder.of(ConversationReset)) == 1
    assert [m.role for m in backend.calls[1]["messages"]] == ["system", "user"]


def test_reset_during_an_answer_discards_that_answer(events, recorder):
    backend = FakeBackend(tokens=("Old", " answer"), gate_after=0)
    assistant = make(events, backend)

    assert assistant.submit("old question")
    assert backend.reached_gate.wait(WAIT)
    assistant.reset()
    backend.gate.set()
    assert assistant.wait_until_idle(WAIT)

    follow_up = FakeBackend()
    assistant._backend = follow_up
    ask(assistant, "new question")
    assert [m.role for m in follow_up.calls[0]["messages"]] == ["system", "user"]


# --------------------------------------------------------------- robustness
def test_a_failing_event_handler_does_not_break_the_answer(events, recorder):
    def broken(event):
        raise RuntimeError("UI bug")

    events.subscribe(AnswerToken, broken)
    assistant = make(events, FakeBackend())
    ask(assistant, "Hi")

    assert recorder.of(AnswerFinished)[0].text == "Hello world"


def test_a_handler_can_submit_the_next_question_when_idle(events, recorder):
    backend = FakeBackend(tokens=("ok",))
    assistant = make(events, backend)
    fired, results = [], []

    def on_idle(event):
        if event.state is AssistantState.IDLE and not fired:
            fired.append(True)  # set BEFORE submitting: the follow-up's own idle event comes quickly
            results.append(assistant.submit("follow-up"))

    events.subscribe(StateChanged, on_idle)
    ask(assistant, "first")  # waits for the whole chain, including the follow-up

    assert results == [True]
    assert len(backend.calls) == 2
    assert len(recorder.of(AnswerFinished)) == 2


def test_wait_until_idle_cannot_be_called_from_a_handler(events):
    assistant = make(events, FakeBackend())
    problems = []

    def bad_handler(event):
        try:
            assistant.wait_until_idle(0.1)
        except RuntimeError as exc:
            problems.append(str(exc))

    events.subscribe(AnswerFinished, bad_handler)
    ask(assistant, "Hi")

    assert problems and "event handler" in problems[0]
