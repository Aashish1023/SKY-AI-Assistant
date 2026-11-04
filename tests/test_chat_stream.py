"""Tests for OllamaApi.chat_stream, using httpx's fake transport (no real server)."""
import json
import threading

import httpx
import pytest

from app.ai.ollama_client import (
    ChatMessage,
    ChatStats,
    OllamaApi,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaUnavailableError,
)

MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")]
SETTINGS = {"model": "llama3.2:3b", "num_ctx": 4096, "temperature": 0.7, "keep_alive": "10m"}


def token(text):
    return {"model": "llama3.2:3b", "message": {"role": "assistant", "content": text}, "done": False}


FINAL = {
    "model": "llama3.2:3b",
    "message": {"role": "assistant", "content": ""},
    "done": True,
    "done_reason": "stop",
    "total_duration": 9_000_000_000,
    "load_duration": 6_000_000,
    "prompt_eval_count": 38,
    "prompt_eval_duration": 1_150_000_000,
    "eval_count": 73,
    "eval_duration": 7_850_000_000,
}


def ndjson(*objects):
    return "".join(json.dumps(obj) + "\n" for obj in objects).encode()


def make_api(handler):
    return OllamaApi("http://127.0.0.1:11434", transport=httpx.MockTransport(handler))


def stream_of(*objects):
    return make_api(lambda request: httpx.Response(200, content=ndjson(*objects)))


class TrackingStream(httpx.SyncByteStream):
    """A response body that records how much was read and whether it was closed."""

    def __init__(self, lines):
        self.lines = lines
        self.read_count = 0
        self.closed = False

    def __iter__(self):
        for line in self.lines:
            self.read_count += 1
            yield line

    def close(self):
        self.closed = True


def tracking_api(*objects):
    body = TrackingStream([json.dumps(obj).encode() + b"\n" for obj in objects])
    return make_api(lambda request: httpx.Response(200, stream=body)), body


# ------------------------------------------------------------------ happy path
def test_streams_text_in_order_and_ends_with_stats():
    api = stream_of(token("Hel"), token("lo"), token("!"), FINAL)

    chunks = list(api.chat_stream(MESSAGES, **SETTINGS))

    assert "".join(c.text for c in chunks) == "Hello!"
    assert [c.done for c in chunks] == [False, False, False, True]
    final = chunks[-1]
    assert final.done_reason == "stop"
    assert final.stats.output_tokens == 73
    assert final.stats.prompt_tokens == 38
    assert final.stats.output_tokens_per_s == pytest.approx(9.3, abs=0.01)  # same as your measurement
    assert final.stats.prompt_tokens_per_s == pytest.approx(33.0, abs=0.1)
    assert final.stats.total_s == pytest.approx(9.0)


def test_request_body_carries_messages_and_options():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ndjson(FINAL))

    list(make_api(handler).chat_stream(MESSAGES, **SETTINGS))

    body = seen["body"]
    assert seen["path"] == "/api/chat"
    assert body["model"] == "llama3.2:3b"
    assert body["stream"] is True
    assert body["keep_alive"] == "10m"
    assert body["options"] == {"num_ctx": 4096, "temperature": 0.7}
    assert body["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hi"},
    ]
    assert "think" not in body  # only sent when explicitly requested


def test_think_flag_is_sent_when_requested():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ndjson(FINAL))

    list(make_api(handler).chat_stream(MESSAGES, think=False, **SETTINGS))

    assert seen["body"]["think"] is False


def test_blank_lines_and_unknown_fields_are_ignored():
    raw = b"\n" + ndjson({**token("Hi"), "surprise": 1}) + b"\n\n" + ndjson(FINAL)
    api = make_api(lambda request: httpx.Response(200, content=raw))

    chunks = list(api.chat_stream(MESSAGES, **SETTINGS))

    assert "".join(c.text for c in chunks) == "Hi"


def test_non_text_content_is_treated_as_empty():
    api = stream_of({"message": {"content": None}, "done": False}, FINAL)

    assert [c.text for c in api.chat_stream(MESSAGES, **SETTINGS)] == ["", ""]


# ---------------------------------------------------------------- cancelling
def test_cancel_event_stops_reading_and_closes_the_connection():
    api, body = tracking_api(*[token(str(i)) for i in range(20)], FINAL)
    cancel = threading.Event()

    stream = api.chat_stream(MESSAGES, cancel=cancel, **SETTINGS)
    assert next(stream).text == "0"
    assert next(stream).text == "1"
    cancel.set()

    assert list(stream) == []  # ends quietly: a cancel is not an error
    assert body.closed
    assert body.read_count < 21  # most of the answer was never read


def test_closing_the_generator_closes_the_connection():
    api, body = tracking_api(token("a"), token("b"), FINAL)

    stream = api.chat_stream(MESSAGES, **SETTINGS)
    next(stream)
    stream.close()

    assert body.closed


# -------------------------------------------------------------------- errors
def test_connection_refused_is_raised_when_iteration_starts():
    def handler(request):
        raise httpx.ConnectError("refused")

    stream = make_api(handler).chat_stream(MESSAGES, **SETTINGS)  # no error yet: it is lazy

    with pytest.raises(OllamaUnavailableError, match="lost the connection"):
        next(stream)


def test_timeout_is_reported_as_no_response():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(OllamaUnavailableError, match="did not respond in time"):
        list(make_api(handler).chat_stream(MESSAGES, **SETTINGS))


def test_missing_model_raises_a_specific_error():
    body = {"error": 'model "nope:1b" not found, try pulling it first'}
    api = make_api(lambda request: httpx.Response(404, json=body))

    with pytest.raises(OllamaModelNotFoundError, match="not found"):
        list(api.chat_stream(MESSAGES, **{**SETTINGS, "model": "nope:1b"}))


def test_other_http_errors_include_ollamas_explanation():
    api = make_api(lambda request: httpx.Response(500, json={"error": "out of memory"}))

    with pytest.raises(OllamaResponseError, match="HTTP 500: out of memory") as info:
        list(api.chat_stream(MESSAGES, **SETTINGS))
    assert not isinstance(info.value, OllamaModelNotFoundError)


def test_a_404_that_is_not_about_a_model_is_not_model_not_found():
    api = make_api(lambda request: httpx.Response(404, text="404 page not found"))

    with pytest.raises(OllamaResponseError) as info:
        list(api.chat_stream(MESSAGES, **SETTINGS))
    assert not isinstance(info.value, OllamaModelNotFoundError)


def test_error_line_inside_the_stream_is_raised():
    api = stream_of(token("Hi"), {"error": "something broke"})

    with pytest.raises(OllamaResponseError, match="something broke"):
        list(api.chat_stream(MESSAGES, **SETTINGS))


def test_invalid_json_line_is_raised():
    api = make_api(lambda request: httpx.Response(200, content=b"not json at all\n"))

    with pytest.raises(OllamaResponseError, match="not valid JSON"):
        list(api.chat_stream(MESSAGES, **SETTINGS))


def test_answer_that_ends_without_a_final_chunk_is_an_error():
    api = stream_of(token("Hel"), token("lo"))  # connection dropped before done=true

    with pytest.raises(OllamaResponseError, match="ended before"):
        list(api.chat_stream(MESSAGES, **SETTINGS))


# ---------------------------------------------------------------- small types
def test_stats_rates_handle_zero_durations():
    stats = ChatStats()

    assert stats.output_tokens_per_s == 0.0
    assert stats.prompt_tokens_per_s == 0.0


def test_chat_message_serialises_to_the_api_shape():
    assert ChatMessage("user", "hello").to_dict() == {"role": "user", "content": "hello"}
