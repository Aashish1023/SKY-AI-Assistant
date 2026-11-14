"""Tests for main.py, the entry point."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import main as sky_main
from app.core.config import SKY_HOME_ENV

ROUTES = {
    "/api/version": {"version": "0.40.11"},
    "/api/tags": {"models": [{"name": "llama3.2:3b", "model": "llama3.2:3b", "size": 2_019_393_189}]},
    "/api/ps": {"models": []},
}


class FakeOllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(ROUTES.get(self.path, {})).encode()
        self.send_response(200 if self.path in ROUTES else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture
def sky_home(tmp_path, monkeypatch):
    """An empty Sky home; main() installs global exception hooks, so restore them afterwards."""
    monkeypatch.setenv(SKY_HOME_ENV, str(tmp_path))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    return tmp_path


@pytest.fixture
def fake_ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def write_config(home, host):
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "data" / "config.json").write_text(json.dumps({"ollama": {"host": host}}), encoding="utf-8")


def test_check_succeeds_against_a_working_ollama(sky_home, fake_ollama):
    write_config(sky_home, fake_ollama)

    assert sky_main.main(["--check"]) == 0


def test_check_fails_when_ollama_is_not_running(sky_home):
    write_config(sky_home, "http://127.0.0.1:9")  # nothing listens on this port

    assert sky_main.main(["--check"]) == 1


def test_a_run_creates_the_config_and_log_files(sky_home):
    write_config(sky_home, "http://127.0.0.1:9")
    (sky_home / "data" / "config.json").unlink()  # start with no config at all

    sky_main.main(["--check"])

    assert (sky_home / "data" / "config.json").exists()
    assert (sky_home / "logs" / "sky.log").exists()


def test_without_arguments_the_window_is_started(sky_home, monkeypatch):
    pytest.importorskip("PySide6")
    started = []
    monkeypatch.setattr("app.ui.app.run_gui", lambda config: started.append(config) or 7)

    assert sky_main.main([]) == 7
    assert len(started) == 1


def test_a_missing_window_library_gives_a_clear_message(sky_home, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "app.ui.app", None)  # makes "import app.ui.app" fail

    assert sky_main.main([]) == 1
    assert "PySide6" in capsys.readouterr().out
