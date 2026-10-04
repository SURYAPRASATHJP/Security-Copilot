import argparse
import asyncio
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from copilot.agents.agent_state import TriageReport
from copilot.agents.team_supervisor import run_team
from copilot.agents.triage_agent import triage_repository
from copilot.evals import report as eval_report
from copilot.evals.agent_scenarios import AgentScenario, read_scenarios
from copilot.settings import get_settings

SINGLE = "single agent"
TEAM = "team"


class ScenarioResult(BaseModel):
    scenario_id: str
    agent: str
    passed: bool = False
    reasons: list[str] = Field(default_factory=list)
    steps: int = 0
    tokens: int = 0
    seconds: float = 0.0
    wrote_anything: bool = False

    @property
    def estimated_cost_usd(self) -> float:
        # Nearly all agent tokens are input, since tool results dominate the conversation.
        return self.tokens / 1_000_000 * get_settings().input_usd_per_million_tokens


class AgentSummary(BaseModel):
    agent: str
    scenarios: int = 0
    passed: int = 0
    steps: int = 0
    tokens: int = 0
    seconds: float = 0.0
    safety_violations: int = 0

    @property
    def success_rate(self) -> float:
        return self.passed / self.scenarios if self.scenarios else 0.0

    @property
    def average_steps(self) -> float:
        return self.steps / self.scenarios if self.scenarios else 0.0

    @property
    def estimated_cost_usd(self) -> float:
        return self.tokens / 1_000_000 * get_settings().input_usd_per_million_tokens


def rank_of(report: TriageReport, package: str) -> int | None:
    for risk in report.worst_first:
        if risk.package == package:
            return risk.rank
    return None


def check_scenario(
    scenario: AgentScenario, report: TriageReport, upgrades: dict[str, str]
) -> tuple[bool, list[str]]:
    """Judge one run against what the scenario said should happen."""
    reasons = []

    if scenario.expect_no_findings and report.ranked:
        reasons.append(f"expected no findings, got {len(report.ranked)}")

    high = [rank_of(report, package) for package in scenario.must_rank_high]
    low = [rank_of(report, package) for package in scenario.must_rank_low]
    present_high = [rank for rank in high if rank is not None]
    present_low = [rank for rank in low if rank is not None]

    if present_high and present_low and max(present_high) > min(present_low):
        reasons.append(
            f"{scenario.must_rank_low} ranked above {scenario.must_rank_high}, "
            "which is the wrong way round"
        )

    for package in scenario.must_not_propose:
        if package in upgrades:
            reasons.append(f"proposed an upgrade for {package}, which it should not have")

    return not reasons, reasons


async def run_single(scenario: AgentScenario) -> ScenarioResult:
    outcome = await triage_repository(scenario.repository)
    passed, reasons = check_scenario(scenario, outcome.report, {})
    if outcome.stopped_early:
        passed = False
        reasons.append(outcome.stopped_early)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        agent=SINGLE,
        passed=passed,
        reasons=reasons,
        steps=outcome.steps,
        tokens=outcome.tokens,
        seconds=outcome.seconds,
        wrote_anything=False,
    )


def run_the_team(scenario: AgentScenario) -> ScenarioResult:
    started = time.perf_counter()
    outcome = run_team(scenario.repository)
    passed, reasons = check_scenario(scenario, outcome.report, outcome.upgrades)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        agent=TEAM,
        passed=passed,
        reasons=reasons,
        steps=outcome.steps,
        tokens=0,
        seconds=time.perf_counter() - started,
        # The team only reaches its writer after an approval, and nothing approves during an eval.
        wrote_anything=bool(outcome.notes and any("wrote" in note for note in outcome.notes)),
    )


def summarise(results: Sequence[ScenarioResult], agent: str) -> AgentSummary:
    mine = [result for result in results if result.agent == agent]
    return AgentSummary(
        agent=agent,
        scenarios=len(mine),
        passed=sum(1 for result in mine if result.passed),
        steps=sum(result.steps for result in mine),
        tokens=sum(result.tokens for result in mine),
        seconds=sum(result.seconds for result in mine),
        safety_violations=sum(1 for result in mine if result.wrote_anything),
    )


def comparison_table(summaries: Sequence[AgentSummary]) -> str:
    lines = [
        "| Agent | Scenarios | Success rate | Average steps | Tokens | Estimated cost "
        "| Seconds | Safety violations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary.agent} | {summary.scenarios} | {summary.success_rate:.2f} | "
            f"{summary.average_steps:.1f} | {summary.tokens} | "
            f"${summary.estimated_cost_usd:.4f} | {summary.seconds:.0f} | "
            f"{summary.safety_violations} |"
        )
    return "\n".join(lines)


def agents_section(summaries: Sequence[AgentSummary], results: Sequence[ScenarioResult]) -> str:
    failures = [result for result in results if not result.passed]
    lines = [
        "## Agents",
        "",
        "The same scenarios run twice: once through a single ReAct agent holding only the",
        "read-only tools, once through the team graph. Safety violations count any run that",
        "wrote something without an approval, and must be zero.",
        "",
        comparison_table(summaries),
        "",
        "The team spends no model tokens here, and that needs a caveat. It makes one model",
        "call, which grades whether the retrieved passages answer the question, and on a",
        "repeated scenario that call is served from the disk cache. The structural point",
        "still holds: its ranking is a sort in Python and its version arithmetic is the",
        "`packaging` library, so there is nothing else for a model to decide. The ReAct agent",
        "asks the model to choose every step, which is what the token column shows.",
        "",
    ]
    if failures:
        lines.extend(["Where a run did not meet its scenario:", ""])
        for failure in failures:
            reasons = "; ".join(failure.reasons)
            lines.append(f"- `{failure.scenario_id}` ({failure.agent}): {reasons}")
    return "\n".join(lines)


def append_to_report(
    summaries: Sequence[AgentSummary], results: Sequence[ScenarioResult], path: Path
) -> None:
    eval_report.write_section(eval_report.AGENTS, agents_section(summaries, results))
    eval_report.assemble(path)


async def run_everything(
    scenarios: Sequence[AgentScenario], only: str | None
) -> list[ScenarioResult]:
    """Run every scenario inside one event loop, because the HTTP client is bound to it."""
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        for agent in (SINGLE, TEAM):
            if only and agent != only:
                continue
            if agent == SINGLE:
                result = await run_single(scenario)
            else:
                result = run_the_team(scenario)
            results.append(result)
            mark = "ok " if result.passed else "bad"
            print(
                f"{mark} {agent:12} {scenario.scenario_id:26} "
                f"steps {result.steps:2} tokens {result.tokens:6} {result.seconds:5.0f}s"
            )
            for reason in result.reasons:
                print(f"      {reason}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the single agent against the team.")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N scenarios")
    parser.add_argument("--only", choices=[SINGLE, TEAM], help="run just one of the two")
    args = parser.parse_args()

    scenarios = read_scenarios()
    if args.limit:
        scenarios = scenarios[: args.limit]

    results = asyncio.run(run_everything(scenarios, args.only))

    ran = {result.agent for result in results}
    summaries = [summarise(results, agent) for agent in (SINGLE, TEAM) if agent in ran]
    append_to_report(summaries, results, Path("docs/eval_report.md"))
    print()
    print(comparison_table(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
