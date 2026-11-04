"""Tests for app.utils.system_info."""
import platform

from app.utils.system_info import get_system_info


def test_reports_plausible_values(tmp_path):
    info = get_system_info(tmp_path)

    assert info.python_version == platform.python_version()
    assert 0 < info.ram_available_gb <= info.ram_total_gb
    assert info.disk_free_gb > 0
    assert info.disk_path == str(tmp_path)
    assert info.logical_cores is None or info.logical_cores >= 1


def test_defaults_to_the_home_folder():
    info = get_system_info()
    assert info.disk_path
    assert info.disk_free_gb > 0
