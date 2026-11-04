"""Startup health checks: can Sky actually talk to its local AI model?

The manager answers four questions and gives a human-readable fix for each
problem it finds:

  1. Is Ollama running?
  2. Is the configured model installed?
  3. Is there enough free RAM to load it?
  4. Is there enough free disk space?

Errors mean "Sky cannot chat yet". Warnings mean "Sky can run, but be careful".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from app.ai.ollama_client import (
    ModelInfo,
    OllamaApi,
    OllamaError,
    normalize_model_name,
)
from app.core.config import OllamaSettings
from app.utils.logger import get_logger
from app.utils.system_info import SystemInfo, get_system_info

logger = get_logger("models")

_GIB = 1024**3

# Rule of thumb measured on this project's laptop: a 2.0 GB model used about 2.6 GB of RAM
# once loaded. We ask for 1.5x the file size, plus headroom for Windows, the UI and speech.
RAM_FACTOR = 1.5
RAM_HEADROOM_GB = 1.0
DEFAULT_REQUIRED_RAM_GB = 4.0  # used when the model size is not known yet
MIN_FREE_DISK_GB = 5.0

CHECK_OLLAMA = "ollama"
CHECK_MODEL = "model"
CHECK_MEMORY = "memory"
CHECK_DISK = "disk"


class Severity(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Check:
    name: str
    severity: Severity
    message: str


@dataclass(frozen=True)
class HealthReport:
    checks: tuple[Check, ...]
    system: SystemInfo

    @property
    def ready(self) -> bool:
        """True when nothing blocks Sky from chatting (warnings are allowed)."""
        return all(check.severity is not Severity.ERROR for check in self.checks)

    @property
    def problems(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.severity is not Severity.OK)

    def get(self, name: str) -> Check | None:
        return next((check for check in self.checks if check.name == name), None)

    def summary(self) -> str:
        return "\n".join(f"[{c.severity.value.upper():<7}] {c.message}" for c in self.checks)


def estimate_required_ram_gb(model_size_bytes: int | None) -> float:
    """Roughly how much free RAM is needed to load a model of this file size."""
    if not model_size_bytes:
        return DEFAULT_REQUIRED_RAM_GB
    return round(model_size_bytes / _GIB * RAM_FACTOR + RAM_HEADROOM_GB, 1)


class ModelManager:
    def __init__(
        self,
        settings: OllamaSettings,
        api: OllamaApi | None = None,
        system_info_provider: Callable[[], SystemInfo] | None = None,
    ) -> None:
        self._settings = settings
        self._owns_api = api is None
        self._api = api or OllamaApi(settings.host, timeout_s=settings.request_timeout_s)
        self._system_info = system_info_provider or get_system_info

    def close(self) -> None:
        if self._owns_api:
            self._api.close()

    def check_health(self) -> HealthReport:
        """Run every check. Never raises: problems are reported, not thrown."""
        settings = self._settings
        system = self._system_info()
        checks: list[Check] = []

        installed: list[ModelInfo] | None = None
        running: list[str] = []

        # 1) Is Ollama running?
        try:
            version = self._api.version()
            installed = self._api.list_models()
        except OllamaError as exc:
            logger.debug("Ollama status check failed: %s", exc)
            checks.append(
                Check(
                    CHECK_OLLAMA,
                    Severity.ERROR,
                    f"Ollama is not responding at {settings.host}. Start it from the Start menu "
                    f"(or run 'ollama serve'), then try again. Details: {exc}",
                )
            )
        else:
            checks.append(
                Check(CHECK_OLLAMA, Severity.OK, f"Ollama {version} is running at {settings.host}")
            )
            try:
                running = self._api.running_models()
            except OllamaError as exc:  # optional information; not a reason to fail
                logger.debug("Could not read loaded models: %s", exc)

        # 2) Is the model installed? (Only answerable when Ollama responded.)
        wanted = normalize_model_name(settings.model)
        model_info: ModelInfo | None = None
        if installed is not None:
            model_info = next((m for m in installed if normalize_model_name(m.name) == wanted), None)
            if model_info is not None:
                size_gb = model_info.size_bytes / _GIB
                checks.append(
                    Check(CHECK_MODEL, Severity.OK, f"Model '{settings.model}' is installed ({size_gb:.1f} GB)")
                )
            else:
                others = ", ".join(m.name for m in installed) or "none"
                checks.append(
                    Check(
                        CHECK_MODEL,
                        Severity.ERROR,
                        f"Model '{settings.model}' is not installed. Install it with: "
                        f"ollama pull {settings.model}   (installed models: {others})",
                    )
                )

        # 3) Enough RAM?
        required = estimate_required_ram_gb(model_info.size_bytes if model_info else None)
        already_loaded = wanted in {normalize_model_name(name) for name in running}
        if already_loaded:
            checks.append(Check(CHECK_MEMORY, Severity.OK, "The model is already loaded in memory"))
        elif system.ram_available_gb >= required:
            checks.append(
                Check(
                    CHECK_MEMORY,
                    Severity.OK,
                    f"{system.ram_available_gb:.1f} GB RAM available (about {required:.1f} GB needed)",
                )
            )
        else:
            checks.append(
                Check(
                    CHECK_MEMORY,
                    Severity.WARNING,
                    f"Only {system.ram_available_gb:.1f} GB RAM is available but about {required:.1f} GB "
                    f"is recommended for '{settings.model}'. Close other programs or choose a smaller model.",
                )
            )

        # 4) Enough disk space?
        if system.disk_free_gb >= MIN_FREE_DISK_GB:
            checks.append(Check(CHECK_DISK, Severity.OK, f"{system.disk_free_gb:.1f} GB free disk space"))
        else:
            checks.append(
                Check(
                    CHECK_DISK,
                    Severity.WARNING,
                    f"Only {system.disk_free_gb:.1f} GB of disk space is free (at least "
                    f"{MIN_FREE_DISK_GB:.0f} GB is recommended). Free up space before downloading models.",
                )
            )

        return HealthReport(checks=tuple(checks), system=system)
