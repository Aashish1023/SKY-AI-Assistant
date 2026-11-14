"""Carries events from Sky's worker threads onto the UI thread.

Qt widgets may only be touched from the UI thread, but the assistant publishes
its events from a background thread. This bridge subscribes to the event
manager and re-emits each event as a Qt signal. A signal emitted from another
thread is delivered to its slots on the receiver's own thread (queued), which
makes it safe.

Rule: always connect these signals to methods of a QObject (such as a window).
Connecting a plain function would run it on the worker thread instead.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from app.core.event_manager import EventManager
from app.core.events import (
    AnswerFailed,
    AnswerFinished,
    AnswerToken,
    ConversationReset,
    StateChanged,
    UserMessageSubmitted,
)


class QtEventBridge(QObject):
    user_message = Signal(str)
    state_changed = Signal(object)  # AssistantState
    token = Signal(str)
    finished = Signal(object)  # AnswerFinished
    failed = Signal(object)  # AnswerFailed
    reset = Signal()

    def __init__(self, events: EventManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unsubscribers: list[Callable[[], None]] = [
            events.subscribe(UserMessageSubmitted, lambda e: self.user_message.emit(e.text)),
            events.subscribe(StateChanged, lambda e: self.state_changed.emit(e.state)),
            events.subscribe(AnswerToken, lambda e: self.token.emit(e.text)),
            events.subscribe(AnswerFinished, lambda e: self.finished.emit(e)),
            events.subscribe(AnswerFailed, lambda e: self.failed.emit(e)),
            events.subscribe(ConversationReset, lambda e: self.reset.emit()),
        ]

    def disconnect_events(self) -> None:
        """Stop listening. Call this before the window is destroyed."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
