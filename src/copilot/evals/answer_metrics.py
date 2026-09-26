import argparse
import re
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from copilot.evals.build_golden_questions import (
    ANSWER,
    FIXED_VERSION,
    IS_AFFECTED,
    WHAT_IS,
    GoldenQuestion,
    read_questions,
)
from copilot.rag.answer_with_citations import CitedAnswer, answer_question
from copilot.settings import get_settings

# The free Groq tier allows 8K tokens a minute, and one answer costs roughly 1.5K.
SECONDS_BETWEEN_CALLS = 8.0

YES = re.compile(r"\b(yes|is affected|are affected|vulnerable)\b", re.IGNORECASE)
NO = re.compile(r"\b(no|not affected|is not affected|unaffected|safe)\b", re.IGNORECASE)


class AnswerOutcome(BaseModel):
    question_id: str
    kind: str
    answerable: bool
    refused: bool
    correct: bool
    wrong_citations: list[str] = Field(default_factory=list)
    answer: str = ""


class AnswerScore(BaseModel):
    questions: int = 0
    answerable: int = 0
    unanswerable: int = 0
    correct_answers: int = 0
    correct_refusals: int = 0
    answers_with_a_wrong_citation: int = 0
    over_refusals: int = 0
    seconds: float = 0.0

    @property
    def answer_accuracy(self) -> float:
        return self.correct_answers / self.answerable if self.answerable else 0.0

    @property
    def refusal_accuracy(self) -> float:
        return self.correct_refusals / self.unanswerable if self.unanswerable else 0.0

    @property
    def wrong_citation_rate(self) -> float:
        return self.answers_with_a_wrong_citation / self.questions if self.questions else 0.0

    @property
    def over_refusal_rate(self) -> float:
        return self.over_refusals / self.answerable if self.answerable else 0.0


def says_yes(text: str) -> bool | None:
    """Read a yes or no out of a sentence, or None when it says neither clearly."""
    yes = YES.search(text) is not None
    no = NO.search(text) is not None
    if yes == no:
        return None
    return yes


def is_correct(question: GoldenQuestion, answer: CitedAnswer) -> bool:
    """Check an answer against what the advisory itself says, with no model in the loop."""
    if answer.refused:
        return False
    if question.kind == FIXED_VERSION:
        return question.expected_answer in answer.answer
    if question.kind == IS_AFFECTED:
        return says_yes(answer.answer) == (question.expected_answer == "yes")
    if question.kind == WHAT_IS:
        # The summary is prose, so the check here is whether it cited the right advisory.
        return bool(set(question.expected_advisory_ids).intersection(answer.citations))
    return False


def score_one(question: GoldenQuestion, answer: CitedAnswer) -> AnswerOutcome:
    correct = answer.refused if not question.answerable else is_correct(question, answer)
    return AnswerOutcome(
        question_id=question.question_id,
        kind=question.kind,
        answerable=question.answerable,
        refused=answer.refused,
        correct=correct,
        wrong_citations=answer.unverified_citations,
        answer=answer.answer,
    )


def summarise(outcomes: Sequence[AnswerOutcome], seconds: float) -> AnswerScore:
    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    return AnswerScore(
        questions=len(outcomes),
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        correct_answers=sum(1 for o in answerable if o.correct),
        correct_refusals=sum(1 for o in unanswerable if o.refused),
        answers_with_a_wrong_citation=sum(1 for o in outcomes if o.wrong_citations),
        over_refusals=sum(1 for o in answerable if o.refused),
        seconds=seconds,
    )


def answer_table(score: AnswerScore) -> str:
    return "\n".join(
        [
            "| Measure | Value | Of |",
            "| --- | --- | --- |",
            f"| Answer accuracy | {score.answer_accuracy:.3f} | "
            f"{score.correct_answers} of {score.answerable} answerable |",
            f"| Refusal accuracy | {score.refusal_accuracy:.3f} | "
            f"{score.correct_refusals} of {score.unanswerable} unanswerable |",
            f"| Wrong citation rate | {score.wrong_citation_rate:.3f} | "
            f"{score.answers_with_a_wrong_citation} of {score.questions} answers |",
            f"| Over-refusal rate | {score.over_refusal_rate:.3f} | "
            f"{score.over_refusals} of {score.answerable} answerable |",
        ]
    )


def append_to_report(score: AnswerScore, path: Path, outcomes: Sequence[AnswerOutcome]) -> None:
    by_kind: dict[str, list[AnswerOutcome]] = {}
    for outcome in outcomes:
        by_kind.setdefault(outcome.kind, []).append(outcome)

    lines = [
        "",
        "## Answers",
        "",
        f"{score.questions} questions from the answer suite, {score.answerable} with a known",
        f"answer and {score.unanswerable} about packages and CVE numbers that do not exist.",
        "",
        answer_table(score),
        "",
        "Correctness is checked without a model in the loop. A fixed-version answer has to",
        "contain the version the advisory names, an is-affected answer has to agree with the",
        "version comparison, and a what-is answer has to cite the right advisory. Whether the",
        "prose itself is faithful is graded separately by the judge in Phase 3.",
        "",
        "| Question kind | Correct | Asked |",
        "| --- | --- | --- |",
    ]
    for kind, group in sorted(by_kind.items()):
        lines.append(f"| {kind} | {sum(1 for o in group if o.correct)} | {len(group)} |")
    lines.append("")

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing.rstrip("\n") + "\n" + "\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the answer suite.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=SECONDS_BETWEEN_CALLS)
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if ANSWER in question.suites
    ]
    if args.limit:
        questions = questions[: args.limit]

    started = time.perf_counter()
    outcomes = []
    for index, question in enumerate(questions, start=1):
        answer = answer_question(question.question)
        outcome = score_one(question, answer)
        outcomes.append(outcome)
        mark = "ok " if outcome.correct else "bad"
        print(f"{index:3}/{len(questions)} {mark} {question.kind:14} {question.question[:60]}")
        if index < len(questions):
            time.sleep(args.sleep)

    score = summarise(outcomes, time.perf_counter() - started)
    report = Path("docs/eval_report.md")
    append_to_report(score, report, outcomes)

    print()
    print(answer_table(score))
    print(f"\nappended to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
