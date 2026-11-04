"""Builds the messages sent to the model: Sky's persona plus recent conversation.

Two constraints on this laptop shape the design:

1. Every token of the prompt must be processed before the first word of the
   answer. Ollama reuses work it has already done, but only for the part of
   the prompt that is *identical to last time*. So the system prompt never
   changes while Sky runs (nothing like the current time goes in it), and old
   exchanges are removed in batches: the conversation grows with an unchanged
   beginning for several turns, then is cut once, instead of shifting by one
   exchange on every turn.

2. The model has a fixed context window (``num_ctx``). If a prompt exceeds it,
   Ollama silently cuts text from the start, which could remove the persona.
   So we keep the prompt inside a budget ourselves, dropping the oldest
   exchanges first.
"""
from __future__ import annotations

import math
import threading

from app.ai.ollama_client import ChatMessage
from app.core.config import AssistantSettings, OllamaSettings
from app.utils.logger import get_logger

logger = get_logger("prompt")

SYSTEM_PROMPT = (
    "You are {name}, a personal AI assistant running locally on the user's Windows laptop. "
    "Your manner is calm, intelligent, confident, friendly and professional, with a subtle "
    "futuristic tone. Speak naturally, like a capable companion, never like a robot. "
    "Keep answers short, one to three sentences, unless the user asks for detail. "
    "Do not ask questions you do not need to ask. "
    "Be honest: if you do not know something or cannot do it, say so plainly. "
    "You cannot control the computer yet, so never claim to have opened, changed or run anything."
)

CHARS_PER_TOKEN = 3  # deliberately pessimistic: English is about 4, code about 3
MESSAGE_OVERHEAD_TOKENS = 4
MAX_ANSWER_RESERVE_TOKENS = 512  # room left in the context window for the answer itself


def estimate_tokens(message: ChatMessage) -> int:
    """A cheap, slightly pessimistic token estimate (no tokenizer needed)."""
    return math.ceil(len(message.content) / CHARS_PER_TOKEN) + MESSAGE_OVERHEAD_TOKENS


class PromptManager:
    def __init__(self, assistant: AssistantSettings, ollama: OllamaSettings) -> None:
        self._system = ChatMessage("system", SYSTEM_PROMPT.format(name=assistant.name))
        self._max_turns = assistant.history_turns
        self._budget = ollama.num_ctx - min(MAX_ANSWER_RESERVE_TOKENS, ollama.num_ctx // 4)
        self._turns: list[tuple[ChatMessage, ChatMessage]] = []  # (question, answer) pairs
        self._lock = threading.Lock()

    @property
    def system_prompt(self) -> str:
        return self._system.content

    @property
    def turn_count(self) -> int:
        with self._lock:
            return len(self._turns)

    def build(self, user_text: str) -> list[ChatMessage]:
        """Messages to send for a new question. Does not record the question yet."""
        user = ChatMessage("user", user_text)
        with self._lock:
            self._trim_by_count()
            self._trim_by_budget(user)
            history = [message for turn in self._turns for message in turn]
            return [self._system, *history, user]

    def commit(self, user_text: str, answer: str) -> None:
        """Remember a finished exchange. Call only when the question was answered."""
        with self._lock:
            self._turns.append((ChatMessage("user", user_text), ChatMessage("assistant", answer)))

    def reset(self) -> None:
        with self._lock:
            self._turns.clear()

    # -- trimming (call with the lock held) --------------------------------
    def _trim_by_count(self) -> None:
        if len(self._turns) > self._max_turns:
            keep = max(1, self._max_turns // 2)  # cut down to half, so the next cut is several turns away
            dropped = len(self._turns) - keep
            del self._turns[:dropped]
            logger.debug("Dropped %d old exchanges from the prompt (count limit)", dropped)

    def _total_tokens(self, user: ChatMessage) -> int:
        history = sum(estimate_tokens(m) for turn in self._turns for m in turn)
        return estimate_tokens(self._system) + history + estimate_tokens(user)

    def _trim_by_budget(self, user: ChatMessage) -> None:
        if self._total_tokens(user) > self._budget:
            target = self._budget // 2  # again cut well below the limit, not just under it
            dropped = 0
            while self._turns and self._total_tokens(user) > target:
                del self._turns[0]
                dropped += 1
            logger.debug("Dropped %d old exchanges from the prompt (size limit)", dropped)
        if self._total_tokens(user) > self._budget:
            logger.warning(
                "This message alone is about %d tokens; the model's window leaves room for %d. "
                "Ollama may cut the start of the prompt.",
                estimate_tokens(user),
                self._budget,
            )
