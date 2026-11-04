"""Smoke tests: the environment and project layout are sane."""
import sys


def test_python_version_supported():
    assert sys.version_info >= (3, 11)


def test_app_package_importable():
    import app  # noqa: F401