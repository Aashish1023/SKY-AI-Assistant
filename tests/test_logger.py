"""Tests for app.utils.logger."""
import logging
import sys
import threading
from types import SimpleNamespace

from app.utils.logger import (
    LOG_FILE_NAME,
    get_logger,
    install_exception_hook,
    setup_logging,
)


def read_log(log_dir):
    for handler in logging.getLogger("sky").handlers:
        handler.flush()
    return (log_dir / LOG_FILE_NAME).read_text(encoding="utf-8")


def test_get_logger_uses_sky_namespace():
    assert get_logger().name == "sky"
    assert get_logger("ai").name == "sky.ai"
    assert get_logger("sky.ai").name == "sky.ai"


def test_messages_are_written_to_the_log_file(tmp_path):
    log_file = setup_logging(tmp_path / "logs", console=False)
    get_logger("demo").info("hello sky")

    assert log_file == tmp_path / "logs" / LOG_FILE_NAME
    text = read_log(tmp_path / "logs")
    assert "hello sky" in text
    assert "INFO" in text and "sky.demo" in text


def test_level_filters_messages(tmp_path):
    setup_logging(tmp_path, level="WARNING", console=False)
    get_logger("demo").info("quiet message")
    get_logger("demo").warning("loud message")

    text = read_log(tmp_path)
    assert "quiet message" not in text
    assert "loud message" in text


def test_unknown_level_falls_back_to_info(tmp_path):
    setup_logging(tmp_path, level="chatty", console=False)
    get_logger("demo").debug("debug message")
    get_logger("demo").info("info message")

    text = read_log(tmp_path)
    assert "debug message" not in text
    assert "info message" in text


def test_setup_is_idempotent(tmp_path):
    for _ in range(3):
        setup_logging(tmp_path, console=False)
    get_logger("demo").info("only once")

    assert len(logging.getLogger("sky").handlers) == 1
    assert read_log(tmp_path).count("only once") == 1


def test_console_output_can_be_enabled_and_disabled(tmp_path, capsys):
    setup_logging(tmp_path, console=True)
    get_logger("demo").info("visible on console")
    assert "visible on console" in capsys.readouterr().err

    setup_logging(tmp_path, console=False)
    get_logger("demo").info("hidden from console")
    assert "hidden from console" not in capsys.readouterr().err


def test_unwritable_log_folder_falls_back_to_console(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a folder", encoding="utf-8")

    log_file = setup_logging(blocker / "logs", console=False)
    get_logger("demo").error("still logged")

    assert log_file is None
    err = capsys.readouterr().err
    assert "File logging unavailable" in err
    assert "still logged" in err


def test_log_file_rotates(tmp_path):
    setup_logging(tmp_path, max_bytes=500, backup_count=2, console=False)
    for i in range(50):
        get_logger("demo").info("line %02d %s", i, "x" * 80)

    assert (tmp_path / LOG_FILE_NAME).exists()
    assert (tmp_path / f"{LOG_FILE_NAME}.1").exists()


def test_uncaught_exception_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    setup_logging(tmp_path, console=False)
    install_exception_hook()

    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    text = read_log(tmp_path)
    assert "CRITICAL" in text and "boom" in text and "Traceback" in text


def test_worker_thread_exception_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    setup_logging(tmp_path, console=False)
    install_exception_hook()

    args = SimpleNamespace(
        exc_type=RuntimeError,
        exc_value=RuntimeError("worker failed"),
        exc_traceback=None,
        thread=SimpleNamespace(name="ollama-worker"),
    )
    threading.excepthook(args)

    text = read_log(tmp_path)
    assert "worker failed" in text and "ollama-worker" in text


def test_ctrl_c_is_not_logged_as_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    handled = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: handled.append(args))
    setup_logging(tmp_path, console=False)
    install_exception_hook()

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert handled
    assert "CRITICAL" not in read_log(tmp_path)
