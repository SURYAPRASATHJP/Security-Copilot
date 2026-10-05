import json

from copilot.guardrails.demo_limits import (
    ALLOWED_REPOSITORIES,
    DAILY_TOKEN_BUDGET_ENV,
    DEMO_MODE_ENV,
    budget_state,
    daily_budget,
    demo_mode,
    repository_is_allowed,
    tokens_spent_on,
)


def test_demo_mode_is_off_unless_it_is_asked_for(monkeypatch):
    monkeypatch.delenv(DEMO_MODE_ENV, raising=False)
    assert demo_mode() is False
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(DEMO_MODE_ENV, value)
        assert demo_mode() is True


def test_any_repository_is_allowed_when_demo_mode_is_off(monkeypatch):
    monkeypatch.delenv(DEMO_MODE_ENV, raising=False)
    assert repository_is_allowed("/somewhere/else") is True


def test_demo_mode_allows_only_the_demo_repository(monkeypatch):
    monkeypatch.setenv(DEMO_MODE_ENV, "1")
    for allowed in ALLOWED_REPOSITORIES:
        assert repository_is_allowed(allowed) is True
    assert repository_is_allowed("/Users/someone/private-work") is False
    assert repository_is_allowed("https://github.com/someone/else") is False


def test_a_trailing_slash_or_git_suffix_does_not_slip_past(monkeypatch):
    monkeypatch.setenv(DEMO_MODE_ENV, "1")
    assert repository_is_allowed("SURYAPRASATHJP/vulnerable-demo-app.git") is True
    assert repository_is_allowed("https://github.com/someone/else.git") is False


def test_the_budget_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv(DAILY_TOKEN_BUDGET_ENV, "5000")
    assert daily_budget() == 5000


def test_a_nonsense_budget_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(DAILY_TOKEN_BUDGET_ENV, "lots")
    assert daily_budget() == 120_000


def write_log(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def test_only_todays_calls_count_towards_the_budget(tmp_path):
    log = write_log(
        tmp_path / "llm_calls.jsonl",
        [
            {"time": "2026-10-08T10:00:00-0700", "input_tokens": 100, "output_tokens": 50},
            {"time": "2026-10-07T10:00:00-0700", "input_tokens": 900, "output_tokens": 900},
        ],
    )
    assert tokens_spent_on("2026-10-08", log) == 150


def test_a_missing_log_means_nothing_has_been_spent(tmp_path):
    assert tokens_spent_on("2026-10-08", tmp_path / "nothing.jsonl") == 0


def test_a_broken_line_in_the_log_is_skipped(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    log.write_text('{broken\n{"time": "2026-10-08T01:00:00-0700", "input_tokens": 10}\n')
    assert tokens_spent_on("2026-10-08", log) == 10


def test_the_budget_reports_what_is_left(tmp_path, monkeypatch):
    monkeypatch.setenv(DAILY_TOKEN_BUDGET_ENV, "1000")
    log = write_log(
        tmp_path / "llm_calls.jsonl",
        [{"time": "2026-10-08T10:00:00-0700", "input_tokens": 300, "output_tokens": 100}],
    )
    state = budget_state(log, today="2026-10-08")
    assert state.spent_today == 400
    assert state.remaining == 600
    assert state.exhausted is False
    assert "600 of 1000" in state.summary


def test_a_spent_budget_says_only_repeated_questions_can_be_answered(tmp_path, monkeypatch):
    monkeypatch.setenv(DAILY_TOKEN_BUDGET_ENV, "100")
    log = write_log(
        tmp_path / "llm_calls.jsonl",
        [{"time": "2026-10-08T10:00:00-0700", "input_tokens": 200, "output_tokens": 0}],
    )
    state = budget_state(log, today="2026-10-08")
    assert state.exhausted is True
    assert state.remaining == 0
    assert "asked before" in state.summary


def test_the_limiter_is_off_unless_the_demo_is_on(monkeypatch):
    monkeypatch.delenv(DEMO_MODE_ENV, raising=False)
    import importlib

    from api import main

    importlib.reload(main)
    assert main.limiter.enabled is False


def test_the_limiter_is_on_for_a_public_demo(monkeypatch):
    monkeypatch.setenv(DEMO_MODE_ENV, "1")
    import importlib

    from api import main

    importlib.reload(main)
    assert main.limiter.enabled is True
    importlib.reload(main)
