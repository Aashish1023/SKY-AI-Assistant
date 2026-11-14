"""The main Sky window: orb, transcript, input box and controls.

The window never talks to the model itself. It asks the assistant core to do
things (submit, cancel, reset) and reacts to the events it publishes, which
reach it through the Qt bridge on the UI thread.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ai.model_manager import HealthReport, Severity
from app.core.assistant import Assistant
from app.core.config import SkyConfig
from app.core.events import AnswerFailed, AnswerFinished, AssistantState
from app.ui.chat_view import ChatView
from app.ui.orb import AssistantOrb
from app.ui.qt_bridge import QtEventBridge
from app.utils.logger import get_logger

logger = get_logger("window")

STATE_TEXT = {
    AssistantState.IDLE: "READY",
    AssistantState.THINKING: "THINKING",
    AssistantState.RESPONDING: "RESPONDING",
}


class MainWindow(QMainWindow):
    # Emitted from the health-check thread; delivered to _on_health on the UI thread.
    health_ready = Signal(object)

    def __init__(
        self,
        config: SkyConfig,
        assistant: Assistant,
        bridge: QtEventBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._assistant = assistant
        self._bridge = bridge
        self.health_report: HealthReport | None = None

        self.setWindowTitle(config.assistant.name)
        self.resize(780, 760)
        self.setMinimumSize(560, 560)

        self._build_ui()
        self._connect_signals()
        self._apply_state(AssistantState.IDLE)
        self.chat.add_notice(f"{config.assistant.name} is online. Model: {config.ollama.model}.")

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)

        # header: name on the left, model on the right
        header = QHBoxLayout()
        title = QLabel(self._config.assistant.name.upper())
        title.setObjectName("title")
        title_font = QFont(title.font())
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 160)
        title.setFont(title_font)
        self.model_label = QLabel(self._config.ollama.model)
        self.model_label.setObjectName("model")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.model_label)
        layout.addLayout(header)

        # orb with its state label underneath
        self.orb = AssistantOrb()
        self.orb.setFixedSize(150, 150)
        self.state_label = QLabel()
        self.state_label.setObjectName("stateLabel")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_font = QFont(self.state_label.font())
        label_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 160)
        self.state_label.setFont(label_font)
        layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.state_label)

        # transcript
        self.chat = ChatView()
        layout.addWidget(self.chat, stretch=1)

        # input row
        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText(f"Message {self._config.assistant.name}...")
        self.send_button = QPushButton("Send")
        self.send_button.setProperty("role", "primary")
        self.send_button.setToolTip("Send the message (Enter)")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Stop the current answer (Esc)")
        self.new_button = QPushButton("New")
        self.new_button.setToolTip("Start a new conversation (Ctrl+N)")
        row.addWidget(self.input, stretch=1)
        row.addWidget(self.send_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.new_button)
        layout.addLayout(row)

        # status line
        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

    def _connect_signals(self) -> None:
        # user actions
        self.send_button.clicked.connect(self.submit_text)
        self.input.returnPressed.connect(self.submit_text)
        self.stop_button.clicked.connect(self.stop_answer)
        self.new_button.clicked.connect(self.new_conversation)
        QShortcut(QKeySequence("Escape"), self, activated=self.stop_answer)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_conversation)

        # events from the assistant (these arrive on the UI thread via the bridge)
        bridge = self._bridge
        bridge.user_message.connect(self._on_user_message)
        bridge.state_changed.connect(self._on_state)
        bridge.token.connect(self._on_token)
        bridge.finished.connect(self._on_finished)
        bridge.failed.connect(self._on_failed)
        bridge.reset.connect(self._on_reset)
        self.health_ready.connect(self._on_health)

    # ------------------------------------------------------------ user actions
    @Slot()
    def submit_text(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        if self._assistant.submit(text):
            self.input.clear()
        # If Sky is busy the text stays in the box, so nothing the user typed is lost.

    @Slot()
    def stop_answer(self) -> None:
        self._assistant.cancel()

    @Slot()
    def new_conversation(self) -> None:
        self._assistant.reset()

    # ---------------------------------------------------------- health check
    def request_health_check(self, check: Callable[[], HealthReport]) -> None:
        """Run ``check`` on a background thread; the result is shown when it arrives."""
        self.status_label.setText("Checking the language model...")

        def work() -> None:
            try:
                report = check()
            except Exception:
                logger.exception("Health check crashed")
                return
            self.health_ready.emit(report)

        threading.Thread(target=work, name="sky-health", daemon=True).start()

    @Slot(object)
    def _on_health(self, report: HealthReport) -> None:
        self.health_report = report
        for check in report.problems:
            self.chat.add_notice(check.message, "error" if check.severity is Severity.ERROR else "warning")
        if report.ready:
            self.status_label.setText("Ready")
        else:
            self.status_label.setText("Not ready: see the messages above")

    # ---------------------------------------------------- assistant events
    @Slot(str)
    def _on_user_message(self, text: str) -> None:
        self.chat.add_user_message(text)

    @Slot(object)
    def _on_state(self, state: AssistantState) -> None:
        self._apply_state(state)

    @Slot(str)
    def _on_token(self, text: str) -> None:
        self.chat.append_sky_text(text, label=self._config.assistant.name.upper())

    @Slot(object)
    def _on_finished(self, event: AnswerFinished) -> None:
        self.chat.end_sky_message()
        if event.cancelled:
            self.chat.add_notice("Stopped.")
            self.status_label.setText("Last answer was stopped")
        elif event.stats is not None:
            stats = event.stats
            self.status_label.setText(
                f"Last answer: {stats.output_tokens_per_s:.1f} tok/s  |  "
                f"prompt {stats.prompt_tokens} tokens in {stats.prompt_s:.1f}s"
            )

    @Slot(object)
    def _on_failed(self, event: AnswerFailed) -> None:
        self.chat.add_notice(event.message, "error")
        self.status_label.setText("The last question could not be answered")

    @Slot()
    def _on_reset(self) -> None:
        self.chat.clear_transcript()
        self.chat.add_notice("New conversation.")
        self.status_label.setText("")

    def _apply_state(self, state: AssistantState) -> None:
        busy = state is not AssistantState.IDLE
        self.orb.set_state(state)
        self.state_label.setText(STATE_TEXT[state])
        self.send_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        if not busy:
            self.input.setFocus()

    # ---------------------------------------------------------------- closing
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt naming)
        self._assistant.shutdown(timeout=3.0)  # stop any answer; Ollama stops when the connection closes
        self._bridge.disconnect_events()
        super().closeEvent(event)
