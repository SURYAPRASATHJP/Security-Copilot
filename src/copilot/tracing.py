import os

import httpx
from pydantic import BaseModel

PHOENIX_UI = "http://localhost:6006"
PHOENIX_ENDPOINT = f"{PHOENIX_UI}/v1/traces"
PROJECT_NAME = "security-copilot"
TRACING_ENV_VAR = "COPILOT_TRACING"
REACHABILITY_TIMEOUT = 2.0


class TracingStatus(BaseModel):
    enabled: bool = False
    endpoint: str = PHOENIX_ENDPOINT
    reason: str = ""

    @property
    def summary(self) -> str:
        return f"tracing to {self.endpoint}" if self.enabled else f"tracing off, {self.reason}"


def tracing_was_asked_for() -> bool:
    return os.environ.get(TRACING_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def phoenix_is_running(ui_url: str = PHOENIX_UI) -> bool:
    """Check for a local Phoenix before trying to send it anything."""
    try:
        return httpx.get(ui_url, timeout=REACHABILITY_TIMEOUT).status_code < 500
    except httpx.HTTPError:
        return False


def start_tracing(
    project_name: str = PROJECT_NAME,
    endpoint: str = PHOENIX_ENDPOINT,
    force: bool = False,
) -> TracingStatus:
    """Send every LLM call, search and agent step to a local Phoenix, if one is there.

    Tracing is opt-in and never fatal: a missing Phoenix leaves the application running
    exactly as it would without it.
    """
    if not force and not tracing_was_asked_for():
        return TracingStatus(reason=f"{TRACING_ENV_VAR} is not set")

    if not phoenix_is_running(endpoint.removesuffix("/v1/traces")):
        return TracingStatus(
            endpoint=endpoint,
            reason="no Phoenix is listening, start it with uvx arize-phoenix serve",
        )

    try:
        from phoenix.otel import register

        register(project_name=project_name, endpoint=endpoint, auto_instrument=True)
    except Exception as error:
        return TracingStatus(endpoint=endpoint, reason=f"{type(error).__name__}: {error}")

    return TracingStatus(enabled=True, endpoint=endpoint)
