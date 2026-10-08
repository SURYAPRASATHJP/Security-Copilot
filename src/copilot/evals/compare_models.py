import argparse
import json
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from copilot.evals import report as eval_report
from copilot.evals.answer_metrics import SECONDS_BETWEEN_CALLS, score_one
from copilot.evals.build_golden_questions import ANSWER, GoldenQuestion, read_questions
from copilot.rag.answer_with_citations import answer_question
from copilot.settings import get_settings

# Groq's free tier has no third chat model this prompt fits: see decisions.md.
CANDIDATES = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
)
DEFAULT_QUESTIONS = 12
SHIPPED = "openai/gpt-oss-120b"


class ModelScore(BaseModel):
    model: str
    questions: int = 0
    correct: int = 0
    refused_correctly: int = 0
    unanswerable: int = 0
    mean_latency_seconds: float = 0.0
    cost_usd: float = 0.0
    failed: str = ""

    @property
    def accuracy(self) -> float:
        return self.correct / self.questions if self.questions else 0.0

    @property
    def cost_per_question_usd(self) -> float:
        return self.cost_usd / self.questions if self.questions else 0.0


def calls_for(prompt_name: str, since: int, log_path: Path) -> list[dict]:
    """Return the calls this project logged after a given point in the file."""
    if not log_path.exists():
        return []
    rows = []
    with log_path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < since or not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("prompt_name") == prompt_name:
                rows.append(record)
    return rows


def lines_in(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def score_model(model: str, questions: Sequence[GoldenQuestion], pause: float) -> ModelScore:
    """Ask one model the same questions and measure what came back."""
    log_path = get_settings().llm_call_log
    before = lines_in(log_path)
    score = ModelScore(model=model, questions=len(questions))

    for index, question in enumerate(questions, start=1):
        try:
            answer = answer_question(question.question, model=model, use_cache=False)
        except Exception as error:
            return score.model_copy(
                update={"questions": index - 1, "failed": f"{type(error).__name__}: {error}"}
            )
        outcome = score_one(question, answer)
        if outcome.correct:
            score.correct += 1
        if not question.answerable:
            score.unanswerable += 1
            if answer.refused:
                score.refused_correctly += 1
        if index < len(questions):
            time.sleep(pause)

    calls = calls_for("answer_question", before, log_path)
    if calls:
        score.mean_latency_seconds = sum(c["latency_seconds"] for c in calls) / len(calls)
        score.cost_usd = sum(c["cost_usd"] for c in calls)
    return score


def comparison_table(scores: Sequence[ModelScore]) -> str:
    lines = [
        "| Model | Questions | Accuracy | Correct refusals | Mean latency | Cost per question |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for score in scores:
        refusals = (
            f"{score.refused_correctly} of {score.unanswerable}" if score.unanswerable else "n/a"
        )
        note = f" ({score.failed})" if score.failed else ""
        lines.append(
            f"| {score.model}{note} | {score.questions} | {score.accuracy:.3f} | {refusals} | "
            f"{score.mean_latency_seconds:.2f} s | ${score.cost_per_question_usd:.5f} |"
        )
    return "\n".join(lines)


def pick_winner(scores: Sequence[ModelScore]) -> ModelScore | None:
    """Accuracy decides, and latency only breaks a tie."""
    usable = [score for score in scores if score.questions and not score.failed]
    if not usable:
        return None
    return max(usable, key=lambda score: (score.accuracy, -score.mean_latency_seconds))


def models_section(scores: Sequence[ModelScore], winner: ModelScore | None) -> str:
    lines = [
        "## Models compared",
        "",
        f"The same answer questions put to {len(scores)} models on Groq, through the same prompt",
        "and the same retrieved passages, so the only thing that changes is the model.",
        "",
        comparison_table(scores),
        "",
    ]
    if winner:
        lines.extend(
            [
                f"**{winner.model}** comes out ahead on these questions, at "
                f"{winner.accuracy:.3f} accuracy and ${winner.cost_per_question_usd:.5f} a "
                f"question. {SHIPPED} is the one in use.",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the answer eval across models.")
    parser.add_argument("--limit", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument("--sleep", type=float, default=SECONDS_BETWEEN_CALLS)
    parser.add_argument("--models", nargs="*", default=list(CANDIDATES))
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if ANSWER in question.suites
    ][: args.limit or None]

    scores = []
    for model in args.models:
        print(f"{model}: {len(questions)} questions")
        score = score_model(model, questions, args.sleep)
        scores.append(score)
        if score.failed:
            print(f"  stopped: {score.failed}")
        else:
            print(f"  accuracy {score.accuracy:.3f}, {score.mean_latency_seconds:.2f}s a question")

    winner = pick_winner(scores)
    eval_report.write_section("models", models_section(scores, winner))
    eval_report.assemble()

    print()
    print(comparison_table(scores))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
