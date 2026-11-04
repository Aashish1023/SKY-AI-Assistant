"""Terminal chat with Sky, built on the same assistant core the window will use.

Run from the project folder:

    .\\.venv\\Scripts\\python.exe scripts\\chat_cli.py

Commands:  /quit  exit      /reset  forget the conversation
Press Ctrl+C while Sky is answering to stop that answer (the program keeps running).

Conversation text is never written to the log file; only timing figures are.
This is a developer tool. The real chat window arrives in step 1.6.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow "import app" when this file is run directly from the scripts folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.model_manager import ModelManager  # noqa: E402
from app.ai.ollama_client import ChatStats, OllamaApi  # noqa: E402
from app.core.assistant import Assistant  # noqa: E402
from app.core.config import get_paths, load_config  # noqa: E402
from app.core.event_manager import EventManager  # noqa: E402
from app.core.events import (  # noqa: E402
    AnswerFailed,
    AnswerFinished,
    AnswerToken,
    AssistantState,
    ConversationReset,
    StateChanged,
)
from app.utils.logger import install_exception_hook, setup_logging  # noqa: E402


def describe(stats: ChatStats) -> str:
    return (
        f"{stats.output_tokens} tokens at {stats.output_tokens_per_s:.1f} tok/s | "
        f"prompt {stats.prompt_tokens} tokens in {stats.prompt_s:.1f}s"
    )


def connect_printer(events: EventManager) -> None:
    """Print what the assistant does. These handlers run on the answer thread."""

    def on_state(event: StateChanged) -> None:
        if event.state is AssistantState.THINKING:
            print("Sky > ", end="", flush=True)

    def on_token(event: AnswerToken) -> None:
        print(event.text, end="", flush=True)

    def on_finished(event: AnswerFinished) -> None:
        if event.cancelled:
            print("\n[stopped]\n")
        elif event.stats:
            print(f"\n[{describe(event.stats)}]\n")
        else:
            print("\n")

    def on_failed(event: AnswerFailed) -> None:
        print(f"\n[error] {event.message}\n")

    events.subscribe(StateChanged, on_state)
    events.subscribe(AnswerToken, on_token)
    events.subscribe(AnswerFinished, on_finished)
    events.subscribe(AnswerFailed, on_failed)
    events.subscribe(ConversationReset, lambda e: print("(conversation cleared)\n"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # model answers may contain characters the console can't show
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    paths = get_paths()
    setup_logging(paths.log_dir, console=False)  # keep the terminal clean; details go to the log file
    install_exception_hook()
    config = load_config(paths)
    setup_logging(
        paths.log_dir,
        level=config.log.level,
        max_bytes=config.log.max_bytes,
        backup_count=config.log.backup_count,
        console=False,
    )

    manager = ModelManager(config.ollama)
    try:
        report = manager.check_health()
    finally:
        manager.close()
    if not report.ready:
        print(report.summary())
        return 1

    api = OllamaApi(config.ollama.host, timeout_s=config.ollama.request_timeout_s)
    events = EventManager()
    assistant = Assistant(config, api, events)
    connect_printer(events)

    print(f"Sky ({config.ollama.model}). /quit to exit, /reset to start over, Ctrl+C stops an answer.\n")
    try:
        while True:
            try:
                text = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text == "/quit":
                break
            if text == "/reset":
                assistant.reset()
                continue
            if not assistant.submit(text):
                continue
            try:
                # Wait in short slices: a long blocking wait cannot be interrupted by Ctrl+C on Windows.
                while not assistant.wait_until_idle(timeout=0.2):
                    pass
            except KeyboardInterrupt:
                assistant.cancel()
                while not assistant.wait_until_idle(timeout=0.2):
                    pass
    finally:
        assistant.shutdown()
        api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
