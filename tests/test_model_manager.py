"""Tests for app.ai.model_manager, using a fake Ollama API and fake system info."""
import pytest

from app.ai.model_manager import (
    CHECK_DISK,
    CHECK_MEMORY,
    CHECK_MODEL,
    CHECK_OLLAMA,
    ModelManager,
    Severity,
    estimate_required_ram_gb,
)
from app.ai.ollama_client import ModelInfo, OllamaUnavailableError
from app.core.config import OllamaSettings
from app.utils.system_info import SystemInfo

GIB = 1024**3


class FakeApi:
    def __init__(self, models=None, running=(), version="0.40.11", down=False, ps_fails=False):
        self._models = [ModelInfo("llama3.2:3b", 2 * GIB)] if models is None else models
        self._running = list(running)
        self._version = version
        self._down = down
        self._ps_fails = ps_fails
        self.closed = False

    def version(self):
        if self._down:
            raise OllamaUnavailableError("connection refused")
        return self._version

    def list_models(self):
        if self._down:
            raise OllamaUnavailableError("connection refused")
        return self._models

    def running_models(self):
        if self._ps_fails:
            raise OllamaUnavailableError("ps failed")
        return self._running

    def close(self):
        self.closed = True


def system(ram=8.0, disk=50.0):
    return SystemInfo(
        os_description="TestOS",
        python_version="3.13.5",
        physical_cores=4,
        logical_cores=8,
        ram_total_gb=16.0,
        ram_available_gb=ram,
        disk_path="C:/",
        disk_free_gb=disk,
    )


def run(api=None, ram=8.0, disk=50.0, **settings):
    manager = ModelManager(
        OllamaSettings(**settings),
        api=api or FakeApi(),
        system_info_provider=lambda: system(ram, disk),
    )
    return manager.check_health()


def test_everything_healthy():
    report = run()

    assert report.ready
    assert report.problems == ()
    assert "0.40.11" in report.get(CHECK_OLLAMA).message
    assert "installed" in report.get(CHECK_MODEL).message


def test_ollama_not_running_is_an_error_with_a_fix():
    report = run(api=FakeApi(down=True))

    check = report.get(CHECK_OLLAMA)
    assert not report.ready
    assert check.severity is Severity.ERROR
    assert "ollama serve" in check.message
    assert report.get(CHECK_MODEL) is None  # cannot be checked while Ollama is down


def test_missing_model_is_an_error_that_shows_the_pull_command():
    report = run(api=FakeApi(models=[ModelInfo("qwen3:4b", 3 * GIB)]))

    check = report.get(CHECK_MODEL)
    assert not report.ready
    assert check.severity is Severity.ERROR
    assert "ollama pull llama3.2:3b" in check.message
    assert "qwen3:4b" in check.message  # tells the user what IS installed


def test_model_without_a_tag_matches_latest():
    api = FakeApi(models=[ModelInfo("llama3.2:latest", 2 * GIB)])
    report = run(api=api, model="llama3.2")

    assert report.get(CHECK_MODEL).severity is Severity.OK


def test_low_ram_is_only_a_warning():
    report = run(ram=2.0)

    check = report.get(CHECK_MEMORY)
    assert report.ready
    assert check.severity is Severity.WARNING
    assert "smaller model" in check.message


def test_low_ram_is_fine_when_the_model_is_already_loaded():
    report = run(api=FakeApi(running=["llama3.2:3b"]), ram=1.0)

    assert report.get(CHECK_MEMORY).severity is Severity.OK


def test_low_disk_is_only_a_warning():
    report = run(disk=2.0)

    assert report.ready
    assert report.get(CHECK_DISK).severity is Severity.WARNING


def test_failure_reading_loaded_models_does_not_mark_ollama_down():
    report = run(api=FakeApi(ps_fails=True))

    assert report.get(CHECK_OLLAMA).severity is Severity.OK
    assert report.ready


def test_summary_lists_every_check():
    summary = run(api=FakeApi(down=True)).summary()

    assert "[ERROR  ]" in summary and "[OK     ]" in summary
    assert summary.count("\n") == 2  # ollama, memory, disk


def test_ram_estimate():
    assert estimate_required_ram_gb(None) == 4.0
    assert estimate_required_ram_gb(0) == 4.0
    assert estimate_required_ram_gb(4 * GIB) == 7.0  # 4 * 1.5 + 1


def test_close_only_closes_an_api_the_manager_created():
    api = FakeApi()
    manager = ModelManager(OllamaSettings(), api=api, system_info_provider=lambda: system())
    manager.close()
    assert not api.closed  # we passed it in, so we keep ownership

    owned = ModelManager(OllamaSettings(), system_info_provider=lambda: system())
    owned.close()  # must not raise
