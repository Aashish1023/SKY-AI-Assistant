"""Sky configuration: typed settings, validation, and JSON persistence.

Design goals:
  * Safe defaults that suit a modest laptop (small model, short context).
  * A bad or half-edited config file must never stop Sky from starting.
    Invalid values fall back to their defaults one by one, with a warning.
  * All settings are plain dataclasses, so the rest of the code gets
    autocomplete and type checking instead of loose dictionaries.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.utils.logger import get_logger

logger = get_logger("config")

SKY_HOME_ENV = "SKY_HOME"
CONFIG_FILE_NAME = "config.json"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


# --------------------------------------------------------------------- paths
@dataclass(frozen=True)
class AppPaths:
    """Where Sky keeps its runtime files."""

    home: Path
    data_dir: Path
    log_dir: Path
    config_file: Path
    db_file: Path


def get_paths() -> AppPaths:
    """Resolve Sky's folders.

    By default everything lives inside the project folder. Set the SKY_HOME
    environment variable to relocate it (used by the tests, and later by the
    installed Windows version).
    """
    override = os.environ.get(SKY_HOME_ENV, "").strip()
    project_root = Path(__file__).resolve().parents[2]
    home = Path(override).expanduser().resolve() if override else project_root
    data_dir = home / "data"
    return AppPaths(
        home=home,
        data_dir=data_dir,
        log_dir=home / "logs",
        config_file=data_dir / CONFIG_FILE_NAME,
        db_file=data_dir / "sky.db",
    )


# ------------------------------------------------------------------ settings
def _setting(
    default: Any,
    check: Callable[[Any], bool] | None = None,
    hint: str = "",
) -> Any:
    """Declare a setting with a default and an optional validity check."""
    return field(default=default, metadata={"check": check, "hint": hint})


@dataclass
class OllamaSettings:
    # 127.0.0.1 instead of "localhost": on Windows "localhost" can resolve to IPv6 first and be slow.
    host: str = _setting(
        "http://127.0.0.1:11434",
        lambda v: v.startswith(("http://", "https://")),
        "must start with http:// or https://",
    )
    model: str = _setting("llama3.2:3b", lambda v: bool(v.strip()), "must not be empty")
    # How long Ollama keeps the model in RAM after the last request.
    keep_alive: str = _setting(
        "10m",
        lambda v: re.fullmatch(r"\d+[smh]", v) is not None,
        'use a number plus a unit, e.g. "30s", "10m" or "1h"',
    )
    num_ctx: int = _setting(4096, lambda v: 512 <= v <= 32768, "must be between 512 and 32768")
    temperature: float = _setting(0.7, lambda v: 0.0 <= v <= 2.0, "must be between 0.0 and 2.0")
    request_timeout_s: float = _setting(120.0, lambda v: v > 0, "must be greater than 0")


@dataclass
class AssistantSettings:
    name: str = _setting("Sky", lambda v: bool(v.strip()), "must not be empty")
    # How many recent question/answer pairs are sent to the model each turn.
    history_turns: int = _setting(8, lambda v: 1 <= v <= 50, "must be between 1 and 50")


@dataclass
class LogSettings:
    level: str = _setting(
        "INFO", lambda v: v.upper() in LOG_LEVELS, f"must be one of {', '.join(LOG_LEVELS)}"
    )
    max_bytes: int = _setting(1_000_000, lambda v: v >= 10_000, "must be at least 10000")
    backup_count: int = _setting(3, lambda v: 0 <= v <= 20, "must be between 0 and 20")
    console: bool = _setting(True)


_SECTIONS: dict[str, type] = {
    "ollama": OllamaSettings,
    "assistant": AssistantSettings,
    "log": LogSettings,
}

_INVALID = object()  # sentinel: "this value has the wrong type"
T = TypeVar("T")


def _coerce(value: Any, expected: type) -> Any:
    """Return value converted to the expected type, or _INVALID."""
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is bool:
        return value if isinstance(value, bool) else _INVALID
    if expected is int:
        return value if isinstance(value, int) and not isinstance(value, bool) else _INVALID
    if expected is float:
        return float(value) if is_number and math.isfinite(value) else _INVALID
    if expected is str:
        return value if isinstance(value, str) else _INVALID
    return _INVALID


def _build_section(cls: type[T], raw: Any, section: str) -> T:
    """Build one settings section from raw JSON data, field by field."""
    if raw is None:
        return cls()
    if not isinstance(raw, dict):
        logger.warning("Config section '%s' must be an object; using its defaults", section)
        return cls()

    known = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    for key in raw:
        if key not in known:
            logger.warning("Unknown config key '%s.%s' ignored", section, key)

    values: dict[str, Any] = {}
    for name, spec in known.items():
        if name not in raw:
            continue
        coerced = _coerce(raw[name], type(spec.default))
        check = spec.metadata.get("check")
        try:
            valid = coerced is not _INVALID and (check is None or bool(check(coerced)))
        except Exception:  # a check must never be able to crash startup
            valid = False
        if not valid:
            logger.warning(
                "Invalid config value %s.%s = %r; using default %r. %s",
                section, name, raw[name], spec.default, spec.metadata.get("hint", ""),
            )
            continue
        values[name] = coerced
    return cls(**values)


@dataclass
class SkyConfig:
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    assistant: AssistantSettings = field(default_factory=AssistantSettings)
    log: LogSettings = field(default_factory=LogSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkyConfig:
        for key in data:
            if key not in _SECTIONS:
                logger.warning("Unknown config section '%s' ignored", key)
        return cls(**{name: _build_section(kind, data.get(name), name) for name, kind in _SECTIONS.items()})


# --------------------------------------------------------------- load / save
def save_config(config: SkyConfig, paths: AppPaths | None = None) -> None:
    """Write the config atomically (temp file + replace), so a crash cannot leave half a file."""
    paths = paths or get_paths()
    target = paths.config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(temp, target)


def _try_save(config: SkyConfig, paths: AppPaths) -> None:
    try:
        save_config(config, paths)
    except OSError as exc:
        logger.error("Could not write %s: %s", paths.config_file, exc)


def _back_up_bad_file(path: Path) -> None:
    backup = path.with_name(path.name + ".bad")
    try:
        os.replace(path, backup)
        logger.error("Unreadable config saved as %s", backup)
    except OSError as exc:
        logger.error("Could not back up %s: %s", path, exc)


def load_config(paths: AppPaths | None = None) -> SkyConfig:
    """Load the config. Never raises: any problem results in defaults plus a log entry."""
    paths = paths or get_paths()
    path = paths.config_file

    if not path.exists():
        logger.info("No config file yet; writing defaults to %s", path)
        config = SkyConfig()
        _try_save(config, paths)
        return config

    try:
        # utf-8-sig tolerates the BOM that Windows Notepad may add.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("the top level must be a JSON object")
    except OSError as exc:
        logger.error("Cannot read %s (%s); using defaults for this run", path, exc)
        return SkyConfig()
    except ValueError as exc:  # includes JSONDecodeError and UnicodeDecodeError
        logger.error("Config file %s is not valid (%s); using defaults", path, exc)
        _back_up_bad_file(path)
        config = SkyConfig()
        _try_save(config, paths)
        return config

    logger.info("Loaded config from %s", path)
    return SkyConfig.from_dict(data)
