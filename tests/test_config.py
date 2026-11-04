"""Tests for app.core.config."""
import json
import logging

import pytest

from app.core.config import (
    SKY_HOME_ENV,
    AssistantSettings,
    SkyConfig,
    get_paths,
    load_config,
    save_config,
)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point Sky at an empty temporary folder so tests never touch real data."""
    monkeypatch.setenv(SKY_HOME_ENV, str(tmp_path))
    return get_paths()


def write_config(paths, data):
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(json.dumps(data), encoding="utf-8")


def test_defaults_are_resource_friendly():
    config = SkyConfig()
    assert config.ollama.model == "llama3.2:3b"
    assert config.ollama.host == "http://127.0.0.1:11434"
    assert config.ollama.num_ctx == 4096
    assert config.assistant.name == "Sky"


def test_sky_home_moves_all_paths(paths, tmp_path):
    home = tmp_path.resolve()
    assert paths.home == home
    assert paths.config_file == home / "data" / "config.json"
    assert paths.db_file == home / "data" / "sky.db"
    assert paths.log_dir == home / "logs"


def test_missing_file_creates_default_config(paths):
    config = load_config(paths)

    assert config == SkyConfig()
    assert json.loads(paths.config_file.read_text(encoding="utf-8")) == SkyConfig().to_dict()


def test_save_then_load_round_trips(paths):
    config = SkyConfig()
    config.ollama.model = "qwen3:4b"
    config.assistant.history_turns = 12
    save_config(config, paths)

    assert load_config(paths) == config
    assert not paths.config_file.with_name("config.json.tmp").exists()


def test_partial_file_overrides_only_given_keys(paths):
    write_config(paths, {"ollama": {"model": "qwen3:4b"}})
    config = load_config(paths)

    assert config.ollama.model == "qwen3:4b"
    assert config.ollama.num_ctx == 4096
    assert config.assistant == AssistantSettings()


def test_invalid_value_falls_back_for_that_field_only(paths, caplog):
    write_config(paths, {"ollama": {"temperature": 9.0, "model": "qwen3:4b"}})
    with caplog.at_level(logging.WARNING, logger="sky"):
        config = load_config(paths)

    assert config.ollama.temperature == 0.7
    assert config.ollama.model == "qwen3:4b"
    assert "ollama.temperature" in caplog.text


def test_wrong_types_are_rejected(paths):
    write_config(
        paths,
        {
            "ollama": {"num_ctx": "big", "host": 123},
            "assistant": {"history_turns": True},  # bool must not count as an int
            "log": {"console": "yes"},
        },
    )
    config = load_config(paths)

    assert config == SkyConfig()


def test_integer_is_accepted_for_a_float_setting(paths):
    write_config(paths, {"ollama": {"temperature": 1}})
    config = load_config(paths)

    assert config.ollama.temperature == 1.0
    assert isinstance(config.ollama.temperature, float)


@pytest.mark.parametrize("value", ["30s", "10m", "1h"])
def test_keep_alive_accepts_durations(paths, value):
    write_config(paths, {"ollama": {"keep_alive": value}})
    assert load_config(paths).ollama.keep_alive == value


@pytest.mark.parametrize("value", ["10", "", "ten minutes", "-1", "5 m"])
def test_keep_alive_rejects_bad_values(paths, value):
    write_config(paths, {"ollama": {"keep_alive": value}})
    assert load_config(paths).ollama.keep_alive == "10m"


def test_log_level_is_case_insensitive_but_must_be_known(paths):
    write_config(paths, {"log": {"level": "debug"}})
    assert load_config(paths).log.level == "debug"

    write_config(paths, {"log": {"level": "chatty"}})
    assert load_config(paths).log.level == "INFO"


def test_unknown_keys_are_ignored_with_a_warning(paths, caplog):
    write_config(paths, {"ollama": {"modle": "typo"}, "extra": 1})
    with caplog.at_level(logging.WARNING, logger="sky"):
        config = load_config(paths)

    assert config == SkyConfig()
    assert "modle" in caplog.text and "extra" in caplog.text


def test_section_that_is_not_an_object_uses_defaults(paths):
    write_config(paths, {"ollama": "llama3.2:3b"})
    assert load_config(paths) == SkyConfig()


def test_corrupt_json_is_backed_up_and_defaults_used(paths):
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text("{ this is not json", encoding="utf-8")

    config = load_config(paths)

    assert config == SkyConfig()
    backup = paths.config_file.with_name("config.json.bad")
    assert backup.read_text(encoding="utf-8") == "{ this is not json"
    assert json.loads(paths.config_file.read_text(encoding="utf-8")) == SkyConfig().to_dict()


def test_json_that_is_not_an_object_counts_as_corrupt(paths):
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text("[1, 2, 3]", encoding="utf-8")

    assert load_config(paths) == SkyConfig()
    assert paths.config_file.with_name("config.json.bad").exists()


def test_file_with_utf8_bom_is_accepted(paths):
    """Windows Notepad can save JSON with a BOM at the start."""
    paths.config_file.parent.mkdir(parents=True)
    body = json.dumps({"ollama": {"model": "qwen3:4b"}}).encode("utf-8")
    paths.config_file.write_bytes(b"\xef\xbb\xbf" + body)

    assert load_config(paths).ollama.model == "qwen3:4b"
