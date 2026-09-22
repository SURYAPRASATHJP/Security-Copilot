import sys
from pathlib import Path

import pytest
from tenacity import wait_fixed

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from copilot import llm_client
from copilot.settings import Settings


class FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeCompletion:
    def __init__(self, text: str, prompt_tokens: int = 11, completion_tokens: int = 3):
        message = type("Message", (), {"content": text})()
        self.choices = [type("Choice", (), {"message": message})()]
        self.usage = FakeUsage(prompt_tokens, completion_tokens)


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

        completions = type("Completions", (), {"create": self._create})()
        self.chat = type("Chat", (), {"completions": completions})()

    def _create(self, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0) if self.replies else FakeCompletion("done")
        if isinstance(reply, BaseException):
            raise reply
        return reply


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        groq_api_key="test-key-not-real",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(llm_client, "_BACKOFF", wait_fixed(0))


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace ask_llm with a canned reply so tests never reach the real API."""
    recorded: list[dict] = []

    def reply_with(text: str):
        def fake_ask_llm(messages, json_schema=None, temperature=0, **kwargs):
            recorded.append({"messages": list(messages), "json_schema": json_schema})
            return text

        monkeypatch.setattr(llm_client, "ask_llm", fake_ask_llm)
        return recorded

    return reply_with
