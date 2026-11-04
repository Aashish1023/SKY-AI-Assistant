"""Tests for app.ai.prompt_manager."""
import logging

from app.ai.ollama_client import ChatMessage
from app.ai.prompt_manager import PromptManager, estimate_tokens
from app.core.config import AssistantSettings, OllamaSettings


def manager(history_turns=8, num_ctx=4096, name="Sky"):
    return PromptManager(
        AssistantSettings(name=name, history_turns=history_turns),
        OllamaSettings(num_ctx=num_ctx),
    )


def roles(messages):
    return [m.role for m in messages]


def test_first_prompt_is_system_then_user():
    prompts = manager()
    messages = prompts.build("Hello")

    assert roles(messages) == ["system", "user"]
    assert messages[1].content == "Hello"


def test_system_prompt_uses_the_assistant_name_and_never_changes():
    prompts = manager(name="Nova")

    assert "You are Nova" in prompts.system_prompt
    first = prompts.build("a")[0]
    prompts.commit("a", "b")
    assert prompts.build("c")[0] == first  # identical every time, so the model's cache stays valid


def test_committed_exchanges_are_included_in_order():
    prompts = manager()
    prompts.commit("My name is Andy", "Nice to meet you, Andy.")

    messages = prompts.build("What is my name?")

    assert roles(messages) == ["system", "user", "assistant", "user"]
    assert messages[1].content == "My name is Andy"
    assert messages[3].content == "What is my name?"


def test_build_does_not_record_the_question():
    prompts = manager()
    prompts.build("Never answered")

    assert prompts.turn_count == 0
    assert roles(prompts.build("Next")) == ["system", "user"]


def test_reset_forgets_everything():
    prompts = manager()
    prompts.commit("a", "b")
    prompts.reset()

    assert prompts.turn_count == 0
    assert roles(prompts.build("x")) == ["system", "user"]


def test_old_exchanges_are_dropped_in_batches_not_one_at_a_time():
    prompts = manager(history_turns=4)
    for i in range(4):
        prompts.commit(f"q{i}", f"a{i}")

    # Four exchanges are still allowed: nothing is dropped yet.
    assert prompts.turn_count == 4
    prompts.build("next")
    assert prompts.turn_count == 4

    prompts.commit("q4", "a4")  # now five: over the limit
    messages = prompts.build("q5")

    # Cut down to half the limit (2 exchanges), not to 4.
    assert [m.content for m in messages[1:-1]] == ["q3", "a3", "q4", "a4"]
    assert prompts.turn_count == 2


def test_the_start_of_the_prompt_stays_identical_between_cuts():
    """Ollama can reuse its earlier work only if the new prompt starts with the previous one."""
    prompts = manager(history_turns=4)
    previous_prompt = None
    previous_answer = None
    broken_at = []

    for i in range(12):
        prompt = prompts.build(f"question {i}")
        if previous_prompt is not None:
            expected_start = previous_prompt + [previous_answer]
            if prompt[: len(expected_start)] != expected_start:
                broken_at.append(i)
        previous_prompt = prompt
        previous_answer = ChatMessage("assistant", f"answer {i}")
        prompts.commit(f"question {i}", f"answer {i}")

    # With a limit of 4, the history is cut (down to 2) only when it reaches 5 exchanges:
    # on turns 5, 8 and 11. Cutting one exchange at a time would break the start every
    # turn from 5 onwards.
    assert broken_at == [5, 8, 11]


def test_token_budget_drops_old_exchanges_when_the_window_is_nearly_full():
    prompts = manager(history_turns=50, num_ctx=2048)  # budget: 2048 - 512 = 1536 tokens
    big = "word " * 120  # 600 characters, about 200 estimated tokens
    for _ in range(4):
        prompts.commit(big, big)

    messages = prompts.build(big)

    assert len(messages) < 2 + 8 + 1  # older exchanges were removed
    assert messages[0].role == "system"  # the persona is never the part that gets cut
    assert messages[-1].content == big  # and the new question is always kept
    assert sum(estimate_tokens(m) for m in messages) <= 1536


def test_a_single_oversized_message_is_still_sent_with_a_warning(caplog):
    prompts = manager(num_ctx=1024)  # budget: 1024 - 256 = 768 tokens
    huge = "x" * 5000

    with caplog.at_level(logging.WARNING, logger="sky"):
        messages = prompts.build(huge)

    assert roles(messages) == ["system", "user"]
    assert messages[-1].content == huge  # we never silently edit the user's text
    assert "may cut the start of the prompt" in caplog.text


def test_estimate_is_pessimistic_and_counts_overhead():
    assert estimate_tokens(ChatMessage("user", "x" * 30)) == 10 + 4
    assert estimate_tokens(ChatMessage("user", "")) == 4
