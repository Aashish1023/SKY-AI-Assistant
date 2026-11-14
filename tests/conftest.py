"""Shared pytest setup."""
import os
import time

# Must be set before Qt is first imported: tests draw into memory, never onto the real screen.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from app.utils.logger import shutdown_logging  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_logging():
    """Close log files after every test (open files block cleanup on Windows)."""
    yield
    shutdown_logging()


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test session (Qt allows only one)."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def pump(qapp):
    """Let Qt process events until ``predicate()`` is true (or the timeout passes)."""

    def _pump(predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        qapp.processEvents()
        return bool(predicate())

    return _pump
