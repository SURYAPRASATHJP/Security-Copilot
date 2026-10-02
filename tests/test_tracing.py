import httpx

from copilot import tracing
from copilot.tracing import (
    PHOENIX_ENDPOINT,
    TRACING_ENV_VAR,
    TracingStatus,
    phoenix_is_running,
    start_tracing,
    tracing_was_asked_for,
)


def test_tracing_is_off_unless_it_is_asked_for(monkeypatch):
    monkeypatch.delenv(TRACING_ENV_VAR, raising=False)
    status = start_tracing()
    assert status.enabled is False
    assert TRACING_ENV_VAR in status.reason


def test_the_environment_variable_is_read_generously(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(TRACING_ENV_VAR, value)
        assert tracing_was_asked_for() is True
    for value in ("0", "false", "no", ""):
        monkeypatch.setenv(TRACING_ENV_VAR, value)
        assert tracing_was_asked_for() is False


def test_a_missing_phoenix_is_reported_rather_than_raised(monkeypatch):
    monkeypatch.setenv(TRACING_ENV_VAR, "1")
    monkeypatch.setattr(tracing, "phoenix_is_running", lambda url=None: False)
    status = start_tracing()
    assert status.enabled is False
    assert "uvx arize-phoenix serve" in status.reason


def test_a_failure_while_registering_is_reported_rather_than_raised(monkeypatch):
    monkeypatch.setenv(TRACING_ENV_VAR, "1")
    monkeypatch.setattr(tracing, "phoenix_is_running", lambda url=None: True)

    def explode(**kwargs):
        raise RuntimeError("otel said no")

    import phoenix.otel

    monkeypatch.setattr(phoenix.otel, "register", explode)
    status = start_tracing()
    assert status.enabled is False
    assert "otel said no" in status.reason


def test_an_unreachable_phoenix_is_not_running(monkeypatch):
    def refuse(url, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(tracing.httpx, "get", refuse)
    assert phoenix_is_running("http://localhost:6006") is False


def test_a_responding_phoenix_is_running(monkeypatch):
    class Response:
        status_code = 200

    monkeypatch.setattr(tracing.httpx, "get", lambda url, timeout=None: Response())
    assert phoenix_is_running("http://localhost:6006") is True


def test_the_status_reads_clearly_either_way():
    assert "tracing to" in TracingStatus(enabled=True).summary
    assert "tracing off" in TracingStatus(reason="no reason").summary


def test_the_endpoint_is_the_one_phoenix_listens_on():
    assert PHOENIX_ENDPOINT == "http://localhost:6006/v1/traces"
