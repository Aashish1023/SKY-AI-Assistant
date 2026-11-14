"""Builds Sky's parts, connects them, and runs the Qt event loop."""
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication

from app.ai.model_manager import HealthReport, ModelManager
from app.ai.ollama_client import OllamaApi
from app.core.assistant import Assistant, ChatBackend
from app.core.config import SkyConfig
from app.core.event_manager import EventManager
from app.ui.main_window import MainWindow
from app.ui.qt_bridge import QtEventBridge
from app.ui.theme import build_stylesheet
from app.utils.logger import get_logger

logger = get_logger("app")


@dataclass
class GuiParts:
    """Everything the running application consists of."""

    app: QApplication
    events: EventManager
    assistant: Assistant
    bridge: QtEventBridge
    window: MainWindow
    api: OllamaApi | None  # only set when we created it (and therefore must close it)

    def close(self) -> None:
        self.bridge.disconnect_events()
        if self.api is not None:
            self.api.close()


def create_gui(config: SkyConfig, backend: ChatBackend | None = None) -> GuiParts:
    """Create the window and everything behind it, without starting the event loop.

    ``backend`` lets tests supply a fake language model instead of a real Ollama.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(config.assistant.name)
    app.setStyleSheet(build_stylesheet())

    api = None
    if backend is None:
        api = OllamaApi(config.ollama.host, timeout_s=config.ollama.request_timeout_s)
        backend = api

    events = EventManager()
    assistant = Assistant(config, backend, events)
    bridge = QtEventBridge(events)
    window = MainWindow(config, assistant, bridge)
    return GuiParts(app, events, assistant, bridge, window, api)


def make_health_check(config: SkyConfig) -> Callable[[], HealthReport]:
    def check() -> HealthReport:
        manager = ModelManager(config.ollama)
        try:
            return manager.check_health()
        finally:
            manager.close()

    return check


def run_gui(config: SkyConfig) -> int:
    parts = create_gui(config)
    parts.window.show()
    parts.window.request_health_check(make_health_check(config))
    logger.info("Window shown; entering the event loop")
    try:
        return parts.app.exec()
    finally:
        parts.close()
