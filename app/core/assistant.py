"""The assistant core.

It takes a question, asks the model on a background thread (so a UI never
freezes), and announces everything that happens as events. It knows nothing
about windows, voice or Qt.

Rules it enforces:
  * One answer at a time. A second question while busy is refused.
  * Events are published from the worker thread.
  * A failed question is not remembered; a cancelled one keeps its partial answer.
  * Whatever goes wrong, the assistant returns to IDLE and stays usable.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from typing import Protocol

from app.ai.ollama_client import (
    ChatChunk,
    ChatMessage,
    ChatStats,
    OllamaError,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
)
from app.ai.prompt_manager import PromptManager
from app.core.config import SkyConfig
from app.core.event_manager import EventManager
from app.core.events import (
    AnswerFailed,
    AnswerFinished,
    AnswerToken,
    AssistantState,
    ConversationReset,
    StateChanged,
    UserMessageSubmitted,
)
from app.utils.logger import get_logger

logger = get_logger("assistant")

WORKER_NAME = "sky-answer"


class ChatBackend(Protocol):
    """What the assistant needs from a language-model client (``OllamaApi`` provides it)."""

    def chat_stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        num_ctx: int,
        temperature: float,
        keep_alive: str,
        think: bool | None = None,
        cancel: threading.Event | None = None,
    ) -> Iterator[ChatChunk]: ...


class Assistant:
    def __init__(
        self,
        config: SkyConfig,
        backend: ChatBackend,
        events: EventManager,
        prompts: PromptManager | None = None,
    ) -> None:
        self._config = config
        self._backend = backend
        self._events = events
        self._prompts = prompts or PromptManager(config.assistant, config.ollama)

        self._lock = threading.Lock()
        self._state = AssistantState.IDLE
        self._epoch = 0  # increases on reset, so a stale answer is never saved
        self._cancel = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    # ------------------------------------------------------------- public API
    @property
    def state(self) -> AssistantState:
        with self._lock:
            return self._state

    def submit(self, text: str) -> bool:
        """Start answering. Returns False (and does nothing) if the text is blank or Sky is busy."""
        text = text.strip()
        if not text:
            return False
        with self._lock:
            if self._state is not AssistantState.IDLE:
                logger.info("Ignored a message because the previous one is still being answered")
                return False
            self._state = AssistantState.THINKING  # reserved now, so a second submit is refused
            self._idle.clear()
            self._cancel = threading.Event()  # a fresh flag for every answer
            cancel, epoch = self._cancel, self._epoch
        threading.Thread(
            target=self._run, args=(text, epoch, cancel), name=WORKER_NAME, daemon=True
        ).start()
        return True

    def cancel(self) -> None:
        """Stop the current answer, if any. The partial answer is kept."""
        with self._lock:
            self._cancel.set()

    def reset(self) -> None:
        """Forget the conversation. Also stops an answer in progress and discards it."""
        with self._lock:
            self._epoch += 1
            self._cancel.set()
            self._prompts.reset()
        self._events.publish(ConversationReset())

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until no answer is running. Returns False if the timeout passed first.

        "Idle" is only signalled after the last event of an answer has been
        published, and only if no new answer has started in the meantime.
        Do not call this from an event handler: the handler runs on the answer
        thread, so it would wait for itself.
        """
        if threading.current_thread().name == WORKER_NAME:
            raise RuntimeError("wait_until_idle() must not be called from an event handler")
        return self._idle.wait(timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel anything running and wait briefly for it to stop."""
        self.cancel()
        self.wait_until_idle(timeout)

    # ----------------------------------------------------------- worker thread
    def _run(self, text: str, epoch: int, cancel: threading.Event) -> None:
        events = self._events
        settings = self._config.ollama
        parts: list[str] = []
        stats: ChatStats | None = None
        done_reason: str | None = None
        completed = False  # True once the model reported the answer as finished
        failure: AnswerFailed | None = None

        try:
            events.publish(UserMessageSubmitted(text))
            events.publish(StateChanged(AssistantState.THINKING))

            messages = self._prompts.build(text)
            stream = self._backend.chat_stream(
                messages,
                model=settings.model,
                num_ctx=settings.num_ctx,
                temperature=settings.temperature,
                keep_alive=settings.keep_alive,
                cancel=cancel,
            )
            try:
                for chunk in stream:
                    if chunk.text:
                        if not parts:
                            self._set_state(AssistantState.RESPONDING)
                        parts.append(chunk.text)
                        events.publish(AnswerToken(chunk.text))
                    if chunk.done:
                        completed = True
                        stats, done_reason = chunk.stats, chunk.done_reason
            finally:
                stream.close()  # makes sure the connection to Ollama is released
        except OllamaModelNotFoundError as exc:
            failure = AnswerFailed(
                f"My language model '{settings.model}' is not installed. "
                f"It can be installed with: ollama pull {settings.model}",
                str(exc),
            )
        except OllamaUnavailableError as exc:
            failure = AnswerFailed(
                "I cannot reach my language model right now. Please check that Ollama is running.",
                str(exc),
            )
        except OllamaError as exc:
            failure = AnswerFailed("My language model sent a response I could not understand.", str(exc))
        except Exception as exc:  # a bug must not leave Sky stuck in the "busy" state
            logger.exception("Unexpected error while answering")
            failure = AnswerFailed("Something went wrong while I was working on that.", repr(exc))

        try:
            if failure is not None:
                logger.error("Answer failed: %s", failure.details)
                events.publish(failure)
            else:
                answer = "".join(parts).strip()
                cancelled = cancel.is_set() and not completed
                with self._lock:
                    if answer and epoch == self._epoch:
                        self._prompts.commit(text, answer)
                self._log_stats(stats, cancelled, done_reason)
                events.publish(AnswerFinished(answer, cancelled, done_reason, stats))
        finally:
            with self._lock:
                self._state = AssistantState.IDLE  # from here on a handler may submit the next question
            events.publish(StateChanged(AssistantState.IDLE))
            with self._lock:
                if self._state is AssistantState.IDLE:  # nothing new started meanwhile
                    self._idle.set()

    def _set_state(self, state: AssistantState) -> None:
        with self._lock:
            self._state = state
        self._events.publish(StateChanged(state))

    @staticmethod
    def _log_stats(stats: ChatStats | None, cancelled: bool, done_reason: str | None) -> None:
        if stats is None:
            logger.info("Answer %s (no timing figures)", "cancelled" if cancelled else "finished")
            return
        logger.info(
            "Answer %s: %d tokens at %.1f tok/s | prompt %d tokens in %.1fs | reason=%s",
            "cancelled" if cancelled else "finished",
            stats.output_tokens,
            stats.output_tokens_per_s,
            stats.prompt_tokens,
            stats.prompt_s,
            done_reason,
        )
