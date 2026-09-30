import pytest

from copilot.agents.agent_state import PackageRisk, TriageReport
from copilot.agents.mcp_tools import READ_ONLY_TOOLS, WRITE_TOOLS, only, read_only
from copilot.agents.triage_agent import (
    MAX_STEPS,
    TRIAGE_PROMPT,
    TokenBudgetExceededError,
    budget_guard,
    tokens_used,
    tool_calls_made,
)


class Message:
    def __init__(self, total_tokens=None, tool_calls=None):
        if total_tokens is not None:
            self.usage_metadata = {"total_tokens": total_tokens}
        self.tool_calls = tool_calls or []


class Tool:
    def __init__(self, name):
        self.name = name


ALL_TOOLS = [Tool(name) for name in (*READ_ONLY_TOOLS, *WRITE_TOOLS)]


def test_tokens_are_summed_across_the_conversation():
    assert tokens_used([Message(100), Message(250), Message()]) == 350


def test_a_conversation_with_no_usage_counts_as_zero():
    assert tokens_used([Message(), Message()]) == 0


def test_steps_are_counted_as_tool_calls():
    messages = [
        Message(tool_calls=[{"name": "a"}, {"name": "b"}]),
        Message(tool_calls=[{"name": "c"}]),
    ]
    assert tool_calls_made(messages) == 3


def test_a_conversation_with_no_tool_calls_is_zero_steps():
    assert tool_calls_made([Message(100)]) == 0


def test_the_budget_guard_allows_a_run_under_budget():
    assert budget_guard(1000)({"messages": [Message(900)]}) == {}


def test_the_budget_guard_stops_a_run_over_budget():
    with pytest.raises(TokenBudgetExceededError, match="budget is 1000"):
        budget_guard(1000)({"messages": [Message(900), Message(200)]})


def test_the_agent_is_given_only_the_read_only_tools():
    names = {tool.name for tool in read_only(ALL_TOOLS)}
    assert names == set(READ_ONLY_TOOLS)
    assert not names.intersection(WRITE_TOOLS)


def test_selecting_tools_by_name_ignores_unknown_names():
    assert [tool.name for tool in only(ALL_TOOLS, ["look_up_vulnerabilities", "nope"])] == [
        "look_up_vulnerabilities"
    ]


def test_the_prompt_tells_the_agent_its_step_limit():
    assert str(MAX_STEPS) in TRIAGE_PROMPT.format(max_steps=MAX_STEPS)


def test_the_prompt_forbids_changing_files():
    assert "Do not change any file" in TRIAGE_PROMPT


def test_a_report_orders_its_findings_worst_first():
    report = TriageReport(
        repository="demo",
        ranked=[
            PackageRisk(package="b", advisory_id="GHSA-b", rank=2),
            PackageRisk(package="a", advisory_id="GHSA-a", rank=1),
        ],
    )
    assert [risk.package for risk in report.worst_first] == ["a", "b"]


def test_an_empty_report_is_valid():
    assert TriageReport(repository="demo").worst_first == []
