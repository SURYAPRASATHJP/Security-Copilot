import argparse
import asyncio
import time
from pathlib import Path

from copilot.evals import report as eval_report
from copilot.evals.agent_scenarios import read_scenarios
from copilot.evals.answer_metrics import append_to_report as write_answers
from copilot.evals.answer_metrics import score_one, summarise
from copilot.evals.build_golden_questions import ANSWER, RETRIEVAL, read_questions
from copilot.evals.compare_agents import SINGLE, TEAM, run_everything
from copilot.evals.compare_agents import append_to_report as write_agents
from copilot.evals.compare_agents import summarise as summarise_agents
from copilot.evals.cost_and_latency_report import append_to_report as write_cost
from copilot.evals.cost_and_latency_report import build_report, read_calls
from copilot.evals.retrieval_metrics import score_every_setup
from copilot.evals.retrieval_metrics import write_report as write_retrieval
from copilot.rag.answer_with_citations import answer_question
from copilot.settings import get_settings

PAUSE_BETWEEN_CALLS = 14.0


def run_retrieval() -> None:
    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if RETRIEVAL in question.suites
    ]
    scores = score_every_setup(questions)
    write_retrieval(scores, eval_report.REPORT_PATH, len(questions))


def run_answers(limit: int, pause: float) -> None:
    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if ANSWER in question.suites
    ]
    if limit:
        questions = questions[:limit]

    started = time.perf_counter()
    outcomes = []
    for index, question in enumerate(questions, start=1):
        outcomes.append(score_one(question, answer_question(question.question)))
        print(f"  answers {index}/{len(questions)}")
        if index < len(questions):
            time.sleep(pause)
    write_answers(
        summarise(outcomes, time.perf_counter() - started), eval_report.REPORT_PATH, outcomes
    )


def run_agents(limit: int) -> None:
    every = read_scenarios()
    scenarios = every[:limit] if limit else every
    results = asyncio.run(run_everything(scenarios, None))
    ran = {result.agent for result in results}
    summaries = [summarise_agents(results, agent) for agent in (SINGLE, TEAM) if agent in ran]
    write_agents(summaries, results, eval_report.REPORT_PATH, complete=len(scenarios) == len(every))


def run_cost() -> None:
    write_cost(build_report(read_calls(get_settings().llm_call_log)), eval_report.REPORT_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every eval and rebuild the report.")
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-answers", action="store_true")
    parser.add_argument("--skip-agents", action="store_true")
    parser.add_argument("--answer-limit", type=int, default=0)
    parser.add_argument("--agent-limit", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=PAUSE_BETWEEN_CALLS)
    args = parser.parse_args()

    if not args.skip_retrieval:
        print("retrieval")
        run_retrieval()
    if not args.skip_answers:
        print("answers")
        run_answers(args.answer_limit, args.sleep)
    if not args.skip_agents:
        print("agents")
        run_agents(args.agent_limit)

    print("cost and latency")
    run_cost()

    path = eval_report.assemble(Path(eval_report.REPORT_PATH))
    print(f"\nsections written: {', '.join(eval_report.sections_present())}")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
