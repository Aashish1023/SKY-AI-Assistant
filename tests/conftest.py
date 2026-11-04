"""Shared pytest setup."""
import pytest

from app.utils.logger import shutdown_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    """Close log files after every test (open files block cleanup on Windows)."""
    yield
    shutdown_logging()
