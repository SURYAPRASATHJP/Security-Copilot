import json
import os
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from copilot.settings import get_settings

DEMO_MODE_ENV = "COPILOT_DEMO_MODE"
DAILY_TOKEN_BUDGET_ENV = "COPILOT_DAILY_TOKEN_BUDGET"

# Groq's free tier allows 200,000 tokens a day, and a public demo must not spend all of it.
DEFAULT_DAILY_TOKEN_BUDGET = 120_000

REQUESTS_PER_MINUTE = "20/minute"
ASK_PER_MINUTE = "6/minute"
SCAN_PER_HOUR = "10/hour"

ALLOWED_REPOSITORIES = (
    "demo_vulnerable_app",
    "https://github.com/SURYAPRASATHJP/vulnerable-demo-app",
    "SURYAPRASATHJP/vulnerable-demo-app",
)


class BudgetState(BaseModel):
    spent_today: int = 0
    budget: int = DEFAULT_DAILY_TOKEN_BUDGET

    @property
    def exhausted(self) -> bool:
        return self.spent_today >= self.budget

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent_today)

    @property
    def summary(self) -> str:
        if self.exhausted:
            return (
                f"today's budget of {self.budget} tokens is spent, so only questions that "
                "have been asked before can be answered"
            )
        return f"{self.remaining} of {self.budget} tokens left today"


def demo_mode() -> bool:
    return os.environ.get(DEMO_MODE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def daily_budget() -> int:
    raw = os.environ.get(DAILY_TOKEN_BUDGET_ENV, "").strip()
    try:
        return int(raw) if raw else DEFAULT_DAILY_TOKEN_BUDGET
    except ValueError:
        return DEFAULT_DAILY_TOKEN_BUDGET


def repository_is_allowed(repository: str) -> bool:
    """In demo mode the agent may only touch the repository built for it."""
    if not demo_mode():
        return True
    cleaned = repository.strip().rstrip("/").removesuffix(".git")
    return any(cleaned == allowed.rstrip("/") for allowed in ALLOWED_REPOSITORIES)


def tokens_spent_on(day: str, log_path: Path | None = None) -> int:
    """Add up what today's real calls have cost, from the call log."""
    path = log_path or get_settings().llm_call_log
    if not path.exists():
        return 0

    spent = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(record.get("time", "")).startswith(day):
                spent += int(record.get("input_tokens", 0)) + int(record.get("output_tokens", 0))
    return spent


def budget_state(log_path: Path | None = None, today: str | None = None) -> BudgetState:
    day = today or date.today().isoformat()
    return BudgetState(spent_today=tokens_spent_on(day, log_path), budget=daily_budget())
