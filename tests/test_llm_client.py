import json

import diskcache
import httpx
import pytest
from conftest import FakeClient, FakeCompletion
from openai import InternalServerError, RateLimitError

from copilot import llm_client


def _http_response(status: int, retry_after: str | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after else {}
    return httpx.Response(status, headers=headers, request=request)


def rate_limited(retry_after: str = "0") -> RateLimitError:
    return RateLimitError(
        "rate limit reached", response=_http_response(429, retry_after), body=None
    )


def server_error() -> InternalServerError:
    return InternalServerError("upstream failure", response=_http_response(500), body=None)


@pytest.fixture
def wired(monkeypatch, settings, tmp_path):
    cache = diskcache.Cache(str(tmp_path / "llm_responses"))
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_client, "_response_cache", lambda: cache)

    def install(replies) -> FakeClient:
        client = FakeClient(replies)
        monkeypatch.setattr(llm_client, "_client", lambda: client)
        return client

    return install


QUESTION = [{"role": "user", "content": "Which version of requests fixes CVE-2023-32681?"}]


def test_ask_llm_returns_the_reply_text(wired):
    wired([FakeCompletion("Upgrade to 2.31.0.")])
    assert llm_client.ask_llm(QUESTION) == "Upgrade to 2.31.0."


def test_retries_past_a_rate_limit_then_succeeds(wired, no_backoff):
    client = wired([rate_limited(), rate_limited("1"), FakeCompletion("2.31.0")])
    assert llm_client.ask_llm(QUESTION) == "2.31.0"
    assert client.calls == 3


def test_retries_past_a_server_error(wired, no_backoff):
    client = wired([server_error(), FakeCompletion("recovered")])
    assert llm_client.ask_llm(QUESTION) == "recovered"
    assert client.calls == 2


def test_gives_up_after_five_attempts(wired, no_backoff):
    client = wired([rate_limited() for _ in range(6)])
    with pytest.raises(RateLimitError):
        llm_client.ask_llm(QUESTION)
    assert client.calls == 5


def test_a_bad_request_is_not_retried(wired, no_backoff):
    bad_request = llm_client.APIStatusError("bad request", response=_http_response(400), body=None)
    client = wired([bad_request])
    with pytest.raises(llm_client.APIStatusError):
        llm_client.ask_llm(QUESTION)
    assert client.calls == 1


def test_retry_after_header_sets_the_wait_floor():
    assert llm_client._retry_after_seconds(rate_limited("7")) == 7.0
    assert llm_client._retry_after_seconds(server_error()) is None


def test_second_identical_question_skips_the_api(wired):
    client = wired([FakeCompletion("cached answer")])
    first = llm_client.ask_llm(QUESTION)
    second = llm_client.ask_llm(QUESTION)
    assert first == second == "cached answer"
    assert client.calls == 1


def test_a_different_question_is_not_served_from_cache(wired):
    client = wired([FakeCompletion("first"), FakeCompletion("second")])
    llm_client.ask_llm(QUESTION)
    llm_client.ask_llm([{"role": "user", "content": "What is CVE-2024-3651 about?"}])
    assert client.calls == 2


def test_cache_key_changes_with_temperature_and_schema():
    base = llm_client.cache_key("m", QUESTION, None, 0)
    assert base == llm_client.cache_key("m", QUESTION, None, 0)
    assert base != llm_client.cache_key("m", QUESTION, None, 0.7)
    assert base != llm_client.cache_key("m", QUESTION, {"type": "object"}, 0)
    assert base != llm_client.cache_key("other", QUESTION, None, 0)


def test_json_schema_is_sent_as_a_response_format(wired):
    client = wired([FakeCompletion('{"answer": "2.31.0"}')])
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    llm_client.ask_llm(QUESTION, json_schema=schema)
    assert client.calls == 1
    assert llm_client._response_format(schema)["json_schema"]["schema"] == schema
    assert llm_client._response_format(None) is None


def test_every_real_call_writes_one_log_line(wired, settings):
    wired([FakeCompletion("logged", prompt_tokens=1_000_000, completion_tokens=500_000)])
    llm_client.ask_llm(QUESTION, prompt_name="answer_question")

    lines = settings.llm_call_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["prompt_name"] == "answer_question"
    assert record["input_tokens"] == 1_000_000
    assert record["output_tokens"] == 500_000
    assert record["cost_usd"] == pytest.approx(0.45)
    assert record["latency_seconds"] >= 0


def test_a_cache_hit_is_not_logged_as_a_call(wired, settings):
    wired([FakeCompletion("logged once")])
    llm_client.ask_llm(QUESTION)
    llm_client.ask_llm(QUESTION)
    lines = settings.llm_call_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_no_log_line_leaks_the_api_key(wired, settings):
    wired([FakeCompletion("safe")])
    llm_client.ask_llm(QUESTION)
    assert settings.groq_api_key not in settings.llm_call_log.read_text(encoding="utf-8")
