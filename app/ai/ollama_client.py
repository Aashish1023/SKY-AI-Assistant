"""A thin HTTP client for the local Ollama server.

Ollama's REST API is small and stable, so Sky talks to it directly with httpx.
That gives us full control over timeouts and cancellation (needed later so
that "Sky, stop" can interrupt an answer), and keeps the code easy to test.

Two kinds of calls live here:
  * status calls (version, installed models, loaded models), and
  * ``chat_stream``, which yields the answer piece by piece as it is generated.
"""
from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger("ollama")

# Status calls must answer quickly; a hung Ollama should not freeze startup.
STATUS_TIMEOUT_S = 5.0


class OllamaError(Exception):
    """Base class for every Ollama-related failure."""


class OllamaUnavailableError(OllamaError):
    """Ollama could not be reached (not running, wrong address, or timed out)."""


class OllamaResponseError(OllamaError):
    """Ollama answered, but not with something we understand."""


class OllamaModelNotFoundError(OllamaResponseError):
    """The requested model is not installed. Fix: ``ollama pull <model>``."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: int


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system", "user" or "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatStats:
    """Timing figures Ollama reports at the end of an answer (converted to seconds)."""

    total_s: float = 0.0
    load_s: float = 0.0
    prompt_tokens: int = 0
    prompt_s: float = 0.0
    output_tokens: int = 0
    output_s: float = 0.0

    @property
    def output_tokens_per_s(self) -> float:
        return self.output_tokens / self.output_s if self.output_s > 0 else 0.0

    @property
    def prompt_tokens_per_s(self) -> float:
        return self.prompt_tokens / self.prompt_s if self.prompt_s > 0 else 0.0


@dataclass(frozen=True)
class ChatChunk:
    """One piece of a streamed answer. The last chunk has done=True and carries the stats."""

    text: str = ""
    done: bool = False
    done_reason: str | None = None
    stats: ChatStats | None = None


def normalize_model_name(name: str) -> str:
    """Ollama treats ``llama3.2`` and ``llama3.2:latest`` as the same model."""
    name = name.strip().lower()
    return name if ":" in name else f"{name}:latest"


class OllamaApi:
    def __init__(
        self,
        host: str,
        timeout_s: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self._timeout_s = timeout_s
        self._http = httpx.Client(base_url=self.host, timeout=timeout_s, transport=transport)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OllamaApi:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- status endpoints --------------------------------------------------
    def version(self) -> str:
        data = self._get_json("/api/version")
        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise OllamaResponseError("/api/version did not include a version string")
        return version

    def list_models(self) -> list[ModelInfo]:
        """Models that are downloaded and ready to use."""
        models: list[ModelInfo] = []
        for item in self._get_json("/api/tags").get("models") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("model") or item.get("name")
            if not isinstance(name, str) or not name:
                continue
            size = item.get("size")
            models.append(ModelInfo(name=name, size_bytes=size if isinstance(size, int) else 0))
        return models

    def running_models(self) -> list[str]:
        """Names of models currently loaded in memory."""
        names: list[str] = []
        for item in self._get_json("/api/ps").get("models") or []:
            if isinstance(item, dict):
                name = item.get("model") or item.get("name")
                if isinstance(name, str) and name:
                    names.append(name)
        return names

    # -- chat ----------------------------------------------------------------
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
    ) -> Iterator[ChatChunk]:
        """Yield the answer piece by piece.

        This is a generator, so nothing happens until you start iterating and
        errors are raised from the iteration, not from the call itself.

        To stop early either set ``cancel`` or call ``.close()`` on the
        generator. Both close the connection, and Ollama stops generating when
        the connection drops. Cancelling is noticed when the next piece arrives:
        about 0.1 s once the answer is flowing, but not during the first few
        seconds while Ollama is still reading the prompt.

        ``think`` is left out of the request unless you set it. Some models
        (Qwen3, DeepSeek-R1) "think" before answering, which is slow on a CPU.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.to_dict() for message in messages],
            "stream": True,
            "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "temperature": temperature},
        }
        if think is not None:
            payload["think"] = think

        timeout = httpx.Timeout(self._timeout_s, connect=STATUS_TIMEOUT_S)
        try:
            with self._http.stream("POST", "/api/chat", json=payload, timeout=timeout) as response:
                if response.status_code >= 400:
                    response.read()
                    raise _error_for_status(response)
                for line in response.iter_lines():
                    if cancel is not None and cancel.is_set():
                        logger.info("Chat stream cancelled")
                        return
                    if not line.strip():
                        continue
                    chunk = _parse_chunk(line)
                    yield chunk
                    if chunk.done:
                        return
                raise OllamaResponseError("the answer ended before Ollama finished it")
        except httpx.TimeoutException as exc:
            raise OllamaUnavailableError(f"Ollama did not respond in time ({exc})") from exc
        except (httpx.TransportError, httpx.InvalidURL) as exc:
            raise OllamaUnavailableError(f"lost the connection to Ollama at {self.host} ({exc})") from exc

    # -- internals ---------------------------------------------------------
    def _get_json(self, path: str) -> dict[str, Any]:
        try:
            response = self._http.get(path, timeout=STATUS_TIMEOUT_S)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise OllamaResponseError(f"{path} returned HTTP {exc.response.status_code}") from exc
        except (httpx.TransportError, httpx.InvalidURL) as exc:
            raise OllamaUnavailableError(f"cannot reach Ollama at {self.host} ({exc})") from exc
        except ValueError as exc:  # the body was not valid JSON
            raise OllamaResponseError(f"{path} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise OllamaResponseError(f"{path} returned an unexpected JSON shape")
        return data


# ------------------------------------------------------------------ helpers
def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _seconds(nanoseconds: Any) -> float:
    return _number(nanoseconds) / 1_000_000_000


def _parse_chunk(line: str) -> ChatChunk:
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise OllamaResponseError("Ollama sent a line that is not valid JSON") from exc
    if not isinstance(data, dict):
        raise OllamaResponseError("Ollama sent an unexpected chunk")
    if "error" in data:
        raise OllamaResponseError(f"Ollama reported an error: {data['error']}")

    message = data.get("message")
    text = message.get("content") if isinstance(message, dict) else ""
    done = data.get("done") is True
    reason = data.get("done_reason")
    stats = None
    if done:
        stats = ChatStats(
            total_s=_seconds(data.get("total_duration")),
            load_s=_seconds(data.get("load_duration")),
            prompt_tokens=int(_number(data.get("prompt_eval_count"))),
            prompt_s=_seconds(data.get("prompt_eval_duration")),
            output_tokens=int(_number(data.get("eval_count"))),
            output_s=_seconds(data.get("eval_duration")),
        )
    return ChatChunk(
        text=text if isinstance(text, str) else "",
        done=done,
        done_reason=reason if isinstance(reason, str) else None,
        stats=stats,
    )


def _error_for_status(response: httpx.Response) -> OllamaError:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("error"), str):
            detail = body["error"]
    except ValueError:
        pass
    detail = detail or response.reason_phrase or "no details"

    lowered = detail.lower()
    if response.status_code == 404 and "model" in lowered and "not found" in lowered:
        return OllamaModelNotFoundError(detail)
    return OllamaResponseError(f"Ollama returned HTTP {response.status_code}: {detail}")
