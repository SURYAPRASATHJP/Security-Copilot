import pytest

from copilot.settings import (
    MISSING_KEY_MESSAGE,
    MissingGroqKeyError,
    Settings,
    require_groq_key,
)


def test_model_name_defaults_to_the_groq_hosted_model(settings):
    assert settings.model_name == "openai/gpt-oss-120b"
    assert settings.groq_base_url == "https://api.groq.com/openai/v1"


def test_missing_key_names_the_file_to_edit():
    blank = Settings(groq_api_key="", _env_file=None)
    with pytest.raises(MissingGroqKeyError) as raised:
        require_groq_key(blank)
    assert ".env" in str(raised.value)
    assert str(raised.value) == MISSING_KEY_MESSAGE


def test_whitespace_only_key_counts_as_missing():
    assert Settings(groq_api_key="   ", _env_file=None).has_groq_key() is False


def test_present_key_passes_the_check(settings):
    assert require_groq_key(settings) is settings


def test_log_and_cache_paths_sit_under_the_configured_directories(settings):
    assert settings.llm_call_log == settings.data_dir / "llm_calls.jsonl"
    assert settings.llm_response_cache == settings.cache_dir / "llm_responses"
