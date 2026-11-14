"""Sky entry point.

    python main.py            open the Sky window
    python main.py --check    run the startup health check, print the result and exit
"""
from __future__ import annotations

import argparse
import sys

from app.ai.model_manager import ModelManager, Severity
from app.core.config import SkyConfig, get_paths, load_config
from app.utils.logger import (
    LOG_FILE_NAME,
    get_logger,
    install_exception_hook,
    setup_logging,
    shutdown_logging,
)


def run_health_check(config: SkyConfig) -> int:
    """Check Ollama, the model, RAM and disk; log the findings. Returns 0 if Sky can chat."""
    log = get_logger("main")
    manager = ModelManager(config.ollama)
    try:
        report = manager.check_health()
    finally:
        manager.close()

    system = report.system
    log.info(
        "System: %s | %s cores / %s threads | RAM %.1f GB total, %.1f GB free | disk %.1f GB free",
        system.os_description,
        system.physical_cores,
        system.logical_cores,
        system.ram_total_gb,
        system.ram_available_gb,
        system.disk_free_gb,
    )
    log_by_severity = {Severity.OK: log.info, Severity.WARNING: log.warning, Severity.ERROR: log.error}
    for check in report.checks:
        log_by_severity[check.severity](check.message)

    if report.ready:
        log.info("Sky is ready to chat.")
    else:
        log.error("Sky cannot chat yet. Fix the errors above and run it again.")
    return 0 if report.ready else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sky", description="Sky, a local AI desktop assistant.")
    parser.add_argument(
        "--check", action="store_true", help="run the startup health check and exit (no window)"
    )
    args = parser.parse_args(argv)

    paths = get_paths()

    # 1) Start logging with safe defaults first, so problems found while
    #    reading the config file are recorded too.
    setup_logging(paths.log_dir)
    install_exception_hook()
    log = get_logger("main")

    config = load_config(paths)

    # 2) Re-apply logging using the user's own settings.
    setup_logging(
        paths.log_dir,
        level=config.log.level,
        max_bytes=config.log.max_bytes,
        backup_count=config.log.backup_count,
        console=config.log.console,
    )

    log.info("Sky starting | python=%s", sys.version.split()[0])
    log.info("Config file: %s", paths.config_file)
    log.info("Log file:    %s", paths.log_dir / LOG_FILE_NAME)

    try:
        if args.check:
            return run_health_check(config)
        try:
            from app.ui.app import run_gui
        except ImportError as exc:
            log.error("The window needs PySide6, which could not be loaded: %s", exc)
            print("Could not load the window library (PySide6). Run: pip install -r requirements.txt")
            return 1
        return run_gui(config)
    finally:
        shutdown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
