"""Sky entry point."""
from __future__ import annotations

import sys

from app.ai.model_manager import ModelManager, Severity
from app.core.config import get_paths, load_config
from app.utils.logger import (
    LOG_FILE_NAME,
    get_logger,
    install_exception_hook,
    setup_logging,
    shutdown_logging,
)


def main() -> int:
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

    # 3) Health check: can Sky talk to its local AI model?
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

    log_by_severity = {
        Severity.OK: log.info,
        Severity.WARNING: log.warning,
        Severity.ERROR: log.error,
    }
    for check in report.checks:
        log_by_severity[check.severity](check.message)

    if report.ready:
        log.info("Sky is ready to chat. (The chat window arrives in step 1.6.)")
    else:
        log.error("Sky cannot chat yet. Fix the errors above and run it again.")

    shutdown_logging()
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
