import time
from collections.abc import Sequence

from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from openai import RateLimitError
from pydantic import BaseModel

from copilot.agents.agent_state import TriageReport
from copilot.agents.mcp_tools import load_tools, read_only
from copilot.settings import require_groq_key

MAX_STEPS = 12
TOKEN_BUDGET = 60_000
MAX_RETRIES = 6

TRIAGE_PROMPT = """You triage known vulnerabilities in a Python repository. Work in this order.

1. Scan the repository for its packages.
2. Look up vulnerabilities for those packages. Ask for the worst few, not all of them.
3. For the two or three worst, check whether the code actually uses the package.
4. Find the lowest safe version for those.

Then rank what you found, worst first. A package the code never imports ranks below one it
calls, even when the score is higher. Say why for each. Do not change any file.

Keep every tool call small and stop as soon as you can answer. You have {max_steps} steps."""


class TriageOutcome(BaseModel):
    report: TriageReport
    steps: int = 0
    tokens: int = 0
    seconds: float = 0.0
    stopped_early: str = ""


class TokenBudgetExceededError(RuntimeError):
    pass


def groq_chat_model() -> ChatOpenAI:
    settings = require_groq_key()
    return ChatOpenAI(
        model=settings.model_name,
        base_url=settings.groq_base_url,
        api_key=settings.groq_api_key,
        temperature=0,
        max_retries=MAX_RETRIES,
        timeout=settings.request_timeout_seconds,
    )


def tokens_used(messages: Sequence) -> int:
    return sum(
        (getattr(message, "usage_metadata", None) or {}).get("total_tokens", 0)
        for message in messages
    )


def tool_calls_made(messages: Sequence) -> int:
    return sum(len(getattr(message, "tool_calls", []) or []) for message in messages)


def budget_guard(budget: int):  # noqa: ANN201
    def hook(state: dict) -> dict:
        used = tokens_used(state["messages"])
        if used > budget:
            raise TokenBudgetExceededError(f"{used} tokens used, budget is {budget}")
        return {}

    return hook


async def triage_repository(
    repository: str, max_steps: int = MAX_STEPS, token_budget: int = TOKEN_BUDGET
) -> TriageOutcome:
    """Run one ReAct agent over a repository with only the read-only tools."""
    started = time.perf_counter()
    tools = read_only(await load_tools())
    agent = create_react_agent(
        groq_chat_model(),
        tools,
        prompt=TRIAGE_PROMPT.format(max_steps=max_steps),
        response_format=TriageReport,
        post_model_hook=budget_guard(token_budget),
    )

    question = f"Triage the repository at {repository}."
    state = {"messages": [{"role": "user", "content": question}]}
    stopped_early = ""
    result: dict = {"messages": []}

    try:
        # Streaming keeps the last state, so a run that is cut short still reports what it spent.
        async for snapshot in agent.astream(
            state, config={"recursion_limit": max_steps * 2}, stream_mode="values"
        ):
            result = snapshot
    except GraphRecursionError:
        stopped_early = f"stopped at the {max_steps} step limit"
    except TokenBudgetExceededError as error:
        stopped_early = str(error)
    except RateLimitError as error:
        # The free tier allows 200K tokens a day, and an agent run is not small.
        stopped_early = f"the model's rate limit was reached: {error}"

    report = result.get("structured_response") or TriageReport(repository=repository)
    if not report.repository:
        report = report.model_copy(update={"repository": repository})

    return TriageOutcome(
        report=report,
        steps=tool_calls_made(result.get("messages", [])),
        tokens=tokens_used(result.get("messages", [])),
        seconds=time.perf_counter() - started,
        stopped_early=stopped_early,
    )
