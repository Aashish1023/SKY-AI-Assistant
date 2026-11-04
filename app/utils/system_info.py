"""Hardware and OS facts that Sky uses to warn about low resources."""
from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

import psutil

_GIB = 1024**3


@dataclass(frozen=True)
class SystemInfo:
    os_description: str
    python_version: str
    physical_cores: int | None
    logical_cores: int | None
    ram_total_gb: float
    ram_available_gb: float
    disk_path: str
    disk_free_gb: float


def get_system_info(disk_path: Path | str | None = None) -> SystemInfo:
    """Read the current system state.

    ``disk_path`` selects which drive to report free space for. It defaults to
    the user's home folder, which is where Ollama stores its models on Windows.
    """
    path = Path(disk_path) if disk_path is not None else Path.home()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(path))
    return SystemInfo(
        os_description=platform.platform(),
        python_version=platform.python_version(),
        physical_cores=psutil.cpu_count(logical=False),
        logical_cores=psutil.cpu_count(logical=True),
        ram_total_gb=round(memory.total / _GIB, 1),
        ram_available_gb=round(memory.available / _GIB, 1),
        disk_path=str(path),
        disk_free_gb=round(disk.free / _GIB, 1),
    )
