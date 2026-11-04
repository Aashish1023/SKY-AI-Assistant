"""Logging for Sky.

Everything Sky logs lives under one logger namespace called "sky"
(``sky.config``, ``sky.ai``, ...). Output goes to a rotating log file and,
optionally, to the console.

Typical use::

    from app.utils.logger import get_logger
    log = get_logger("ai")          # -> logger named "sky.ai"
    log.info("Model loaded: %s", name)
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any

LOGGER_NAME = "sky"
LOG_FILE_NAME = "sky.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger inside Sky's namespace."""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def setup_logging(
    log_dir: Path | str,
    level: str = "INFO",
    max_bytes: int = 1_000_000,
    backup_count: int = 3,
    console: bool = True,
) -> Path | None:
    """Configure Sky's logging. Safe to call more than once (it reconfigures).

    Returns the path of the log file, or ``None`` if file logging is
    unavailable (for example, the folder is not writable). In that case Sky
    keeps running and logs to the console instead.
    """
    shutdown_logging()  # remove old handlers so repeated calls never duplicate output

    root = get_logger()
    root.setLevel(_LEVELS.get(str(level).upper(), logging.INFO))
    root.propagate = False
    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)

    log_file: Path | None = None
    file_error: OSError | None = None
    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        log_file = directory / LOG_FILE_NAME
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        file_error = exc
        log_file = None

    # If the file is unavailable we always fall back to the console, so errors are never lost.
    # sys.stderr is None when running under pythonw.exe (no console window), so check for that.
    if (console or file_error is not None) and sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if file_error is not None:
        root.warning("File logging unavailable (%s); logging to console only", file_error)
    return log_file


def shutdown_logging() -> None:
    """Close and remove all of Sky's log handlers."""
    root = get_logger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.NOTSET)
    root.propagate = True


def install_exception_hook() -> None:
    """Record uncaught exceptions (main thread and worker threads) in the log.

    Without this, a crash in a background thread can disappear silently,
    which is especially bad for an assistant that starts with Windows.
    """

    def _log_main_thread(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)  # Ctrl+C is not a crash
            return
        get_logger("uncaught").critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    def _log_worker_thread(args: Any) -> None:
        if args.exc_type is SystemExit:
            return
        thread_name = args.thread.name if args.thread is not None else "unknown"
        get_logger("uncaught").critical(
            "Unhandled exception in thread %s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _log_main_thread
    threading.excepthook = _log_worker_thread
