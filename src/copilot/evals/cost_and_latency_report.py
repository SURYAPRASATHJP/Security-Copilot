import statistics
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from copilot.settings import get_settings

ANSWER_PROMPT = "answer_question"
SCAN_PROMPT = "grade_passages"


class CallRecord(BaseModel):
    time: str = ""
    prompt_name: str = "unnamed"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class PromptStats(BaseModel):
    prompt_name: str
    calls: int = 0
    total_cost_usd: float = 0.0
    mean_cost_usd: float = 0.0
    mean_tokens: float = 0.0
    p50_latency_seconds: float = 0.0
    p95_latency_seconds: float = 0.0


class CostReport(BaseModel):
    calls: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    p50_latency_seconds: float = 0.0
    p95_latency_seconds: float = 0.0
    cost_per_question_usd: float = 0.0
    cost_per_repo_scan_usd: float = 0.0
    by_prompt: list[PromptStats] = Field(default_factory=list)


def read_calls(path: Path) -> list[CallRecord]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(CallRecord.model_validate_json(line))
    return records


def percentile(values: Sequence[float], fraction: float) -> float:
    """Return the value at a fraction of the way through the sorted list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def stats_for(prompt_name: str, calls: Sequence[CallRecord]) -> PromptStats:
    mine = [call for call in calls if call.prompt_name == prompt_name]
    if not mine:
        return PromptStats(prompt_name=prompt_name)
    latencies = [call.latency_seconds for call in mine]
    return PromptStats(
        prompt_name=prompt_name,
        calls=len(mine),
        total_cost_usd=sum(call.cost_usd for call in mine),
        mean_cost_usd=statistics.fmean(call.cost_usd for call in mine),
        mean_tokens=statistics.fmean(call.total_tokens for call in mine),
        p50_latency_seconds=percentile(latencies, 0.50),
        p95_latency_seconds=percentile(latencies, 0.95),
    )


def build_report(calls: Sequence[CallRecord]) -> CostReport:
    """Summarise every real API call the project has made."""
    if not calls:
        return CostReport()

    latencies = [call.latency_seconds for call in calls]
    names = sorted({call.prompt_name for call in calls})
    by_prompt = [stats_for(name, calls) for name in names]
    answer = stats_for(ANSWER_PROMPT, calls)
    scan = stats_for(SCAN_PROMPT, calls)

    return CostReport(
        calls=len(calls),
        total_cost_usd=sum(call.cost_usd for call in calls),
        total_tokens=sum(call.total_tokens for call in calls),
        p50_latency_seconds=percentile(latencies, 0.50),
        p95_latency_seconds=percentile(latencies, 0.95),
        cost_per_question_usd=answer.mean_cost_usd,
        cost_per_repo_scan_usd=scan.mean_cost_usd,
        by_prompt=by_prompt,
    )


def report_table(report: CostReport) -> str:
    lines = [
        "| Measure | Value |",
        "| --- | --- |",
        f"| Real API calls logged | {report.calls} |",
        f"| Total spend | ${report.total_cost_usd:.4f} |",
        f"| p50 latency | {report.p50_latency_seconds:.2f} s |",
        f"| p95 latency | {report.p95_latency_seconds:.2f} s |",
        f"| Cost per answered question | ${report.cost_per_question_usd:.5f} |",
        f"| Cost per repository scan | ${report.cost_per_repo_scan_usd:.5f} |",
        "",
        "| Prompt | Calls | Mean tokens | Mean cost | p50 | p95 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for stats in report.by_prompt:
        lines.append(
            f"| {stats.prompt_name} | {stats.calls} | {stats.mean_tokens:.0f} | "
            f"${stats.mean_cost_usd:.5f} | {stats.p50_latency_seconds:.2f} s | "
            f"{stats.p95_latency_seconds:.2f} s |"
        )
    return "\n".join(lines)


def append_to_report(report: CostReport, path: Path) -> None:
    lines = [
        "",
        "## Cost and latency",
        "",
        "Every real call to the model is logged to `data/llm_calls.jsonl` with its tokens,",
        "latency and cost. Cached replies make no call and appear nowhere here, which is why",
        "the totals are lower than the number of questions asked.",
        "",
        report_table(report),
        "",
    ]
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing.rstrip("\n") + "\n" + "\n".join(lines), encoding="utf-8")


def main() -> int:
    calls = read_calls(get_settings().llm_call_log)
    report = build_report(calls)
    append_to_report(report, Path("docs/eval_report.md"))
    print(report_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
