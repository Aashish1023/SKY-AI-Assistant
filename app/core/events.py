"""The events Sky's components use to talk to each other.

Events are small, immutable records. The assistant core publishes them; the UI,
the voice system and the memory system will subscribe to the ones they need.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.ai.ollama_client import ChatStats


class AssistantState(str, Enum):
    IDLE = "idle"  # waiting for the user
    THINKING = "thinking"  # question received, no answer text yet
    RESPONDING = "responding"  # answer is streaming in


@dataclass(frozen=True)
class Event:
    """Base class. Subscribe to ``Event`` itself to receive everything."""


@dataclass(frozen=True)
class UserMessageSubmitted(Event):
    text: str


@dataclass(frozen=True)
class StateChanged(Event):
    state: AssistantState


@dataclass(frozen=True)
class AnswerToken(Event):
    """A new piece of the answer text."""

    text: str


@dataclass(frozen=True)
class AnswerFinished(Event):
    text: str  # the full answer (may be partial if cancelled)
    cancelled: bool = False
    done_reason: str | None = None
    stats: ChatStats | None = None


@dataclass(frozen=True)
class AnswerFailed(Event):
    message: str  # friendly wording, suitable for showing or speaking
    details: str = ""  # technical detail, for logs and a "details" view


@dataclass(frozen=True)
class ConversationReset(Event):
    pass
