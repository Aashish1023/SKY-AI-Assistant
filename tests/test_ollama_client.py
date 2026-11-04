"""Tests for app.ai.ollama_client, using httpx's built-in fake transport (no real server)."""
import httpx
import pytest

from app.ai.ollama_client import (
    ModelInfo,
    OllamaApi,
    OllamaResponseError,
    OllamaUnavailableError,
    normalize_model_name,
)


def make_api(handler, host="http://127.0.0.1:11434"):
    return OllamaApi(host, transport=httpx.MockTransport(handler))


def test_version_is_read_from_the_api():
    def handler(request):
        assert request.url.path == "/api/version"
        return httpx.Response(200, json={"version": "0.40.11"})

    assert make_api(handler).version() == "0.40.11"


def test_trailing_slash_in_host_is_ignored():
    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/version"
        return httpx.Response(200, json={"version": "1.0"})

    assert make_api(handler, host="http://127.0.0.1:11434/").version() == "1.0"


def test_list_models_returns_names_and_sizes_and_skips_junk():
    payload = {
        "models": [
            {"name": "llama3.2:3b", "model": "llama3.2:3b", "size": 2_019_393_189},
            {"name": "old-style:latest"},  # no "model" key and no size
            {"size": 5},  # no name at all
            "not-a-dict",
        ]
    }
    api = make_api(lambda request: httpx.Response(200, json=payload))

    assert api.list_models() == [
        ModelInfo("llama3.2:3b", 2_019_393_189),
        ModelInfo("old-style:latest", 0),
    ]


def test_list_models_handles_an_empty_library():
    assert make_api(lambda r: httpx.Response(200, json={"models": []})).list_models() == []
    assert make_api(lambda r: httpx.Response(200, json={})).list_models() == []


def test_running_models_lists_loaded_models():
    def handler(request):
        assert request.url.path == "/api/ps"
        return httpx.Response(200, json={"models": [{"model": "llama3.2:3b"}]})

    assert make_api(handler).running_models() == ["llama3.2:3b"]


def test_connection_refused_becomes_unavailable_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(OllamaUnavailableError, match="cannot reach Ollama"):
        make_api(handler).version()


def test_timeout_becomes_unavailable_error():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(OllamaUnavailableError):
        make_api(handler).list_models()


def test_http_error_status_becomes_response_error():
    api = make_api(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(OllamaResponseError, match="HTTP 500"):
        api.version()


def test_invalid_json_becomes_response_error():
    api = make_api(lambda r: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(OllamaResponseError, match="invalid JSON"):
        api.version()


def test_unexpected_json_shape_becomes_response_error():
    api = make_api(lambda r: httpx.Response(200, json=["a", "list"]))
    with pytest.raises(OllamaResponseError, match="unexpected JSON shape"):
        api.version()


def test_missing_version_field_becomes_response_error():
    api = make_api(lambda r: httpx.Response(200, json={"hello": "world"}))
    with pytest.raises(OllamaResponseError, match="version"):
        api.version()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("llama3.2", "llama3.2:latest"),
        ("llama3.2:3b", "llama3.2:3b"),
        ("  Qwen3:4B ", "qwen3:4b"),
    ],
)
def test_normalize_model_name(given, expected):
    assert normalize_model_name(given) == expected
