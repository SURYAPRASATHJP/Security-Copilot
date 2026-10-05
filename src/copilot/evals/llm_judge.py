import argparse
import json
import time
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from copilot import llm_client
from copilot.evals import report as eval_report
from copilot.evals.answer_metrics import SECONDS_BETWEEN_CALLS, score_one
from copilot.evals.build_golden_questions import ANSWER, GoldenQuestion, read_questions
from copilot.prompt_loader import load_prompt
from copilot.rag.answer_with_citations import CitedAnswer, answer_question
from copilot.rag.search_result import SearchResult
from copilot.settings import get_settings

PROMPT_NAME = "judge_answer"
AGREEMENT_THRESHOLD = 0.5

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "number"},
        "correctness": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["faithfulness", "correctness", "reason"],
    "additionalProperties": False,
}


class Judgement(BaseModel):
    faithfulness: float = 0.0
    correctness: float = 0.0
    reason: str = ""

    @property
    def says_correct(self) -> bool:
        return self.correctness >= AGREEMENT_THRESHOLD


class JudgeOutcome(BaseModel):
    question_id: str
    kind: str
    judgement: Judgement
    code_says_correct: bool
    agreed: bool


class JudgeReport(BaseModel):
    judged: int = 0
    mean_faithfulness: float = 0.0
    mean_correctness: float = 0.0
    agreements: int = 0
    seconds: float = 0.0

    @property
    def agreement_rate(self) -> float:
        return self.agreements / self.judged if self.judged else 0.0


def format_passages(passages: Sequence[SearchResult]) -> str:
    if not passages:
        return "No passages were retrieved."
    return "\n\n".join(f"[{p.advisory_id}] {p.chunk.text[:600]}" for p in passages)


def judge_answer(
    question: str, answer: str, passages: Sequence[SearchResult], expected: str
) -> Judgement:
    """Score one answer for faithfulness and correctness, as structured output."""
    filled = (
        load_prompt(PROMPT_NAME)
        .replace("{passages}", format_passages(passages))
        .replace("{question}", question)
        .replace("{expected}", expected)
        .replace("{answer}", answer)
    )
    reply = llm_client.ask_llm(
        [{"role": "user", "content": filled}],
        json_schema=JUDGE_SCHEMA,
        prompt_name=PROMPT_NAME,
    )
    try:
        return Judgement.model_validate(json.loads(reply))
    except (json.JSONDecodeError, ValidationError):
        return Judgement(reason="the judge did not return a readable score")


def judge_one(question: GoldenQuestion, answer: CitedAnswer) -> JudgeOutcome:
    """Grade an answer, and record whether the judge agrees with the deterministic check."""
    judgement = judge_answer(
        question.question, answer.answer, answer.passages, question.expected_answer
    )
    code_says = score_one(question, answer).correct if question.answerable else answer.refused
    return JudgeOutcome(
        question_id=question.question_id,
        kind=question.kind,
        judgement=judgement,
        code_says_correct=code_says,
        agreed=judgement.says_correct == code_says,
    )


def summarise(outcomes: Sequence[JudgeOutcome], seconds: float) -> JudgeReport:
    if not outcomes:
        return JudgeReport(seconds=seconds)
    return JudgeReport(
        judged=len(outcomes),
        mean_faithfulness=sum(o.judgement.faithfulness for o in outcomes) / len(outcomes),
        mean_correctness=sum(o.judgement.correctness for o in outcomes) / len(outcomes),
        agreements=sum(1 for o in outcomes if o.agreed),
        seconds=seconds,
    )


def judge_section(report: JudgeReport, disagreements: Sequence[JudgeOutcome]) -> str:
    lines = [
        "## The judge",
        "",
        "A rubric prompt scores every answer for faithfulness and correctness. The number",
        "that matters is not the score, it is how often the judge agrees with the",
        "deterministic check, because that is what says whether the judge can be trusted on",
        "the questions where no deterministic check exists.",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Answers judged | {report.judged} |",
        f"| Mean faithfulness | {report.mean_faithfulness:.3f} |",
        f"| Mean correctness | {report.mean_correctness:.3f} |",
        f"| Agreement with the deterministic check | {report.agreement_rate:.1%} |",
        "",
    ]
    if disagreements:
        lines.extend(["Where the judge and the code disagreed:", ""])
        for outcome in disagreements[:10]:
            verdict = "judge says right, code says wrong"
            if not outcome.judgement.says_correct:
                verdict = "judge says wrong, code says right"
            lines.append(f"- `{outcome.question_id}`: {verdict}. {outcome.judgement.reason}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade the answers with a rubric judge.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=SECONDS_BETWEEN_CALLS)
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if ANSWER in question.suites
    ][: args.limit or None]

    started = time.perf_counter()
    outcomes = []
    for index, question in enumerate(questions, start=1):
        answer = answer_question(question.question)
        outcome = judge_one(question, answer)
        outcomes.append(outcome)
        mark = "agree" if outcome.agreed else "DIFFER"
        print(
            f"{index:3}/{len(questions)} {mark:7} "
            f"faith {outcome.judgement.faithfulness:.2f} "
            f"correct {outcome.judgement.correctness:.2f}  {question.kind}"
        )
        if index < len(questions):
            time.sleep(args.sleep)

    report = summarise(outcomes, time.perf_counter() - started)
    disagreements = [outcome for outcome in outcomes if not outcome.agreed]
    eval_report.write_section("judge", judge_section(report, disagreements))
    eval_report.assemble()

    print()
    print(f"agreement with the deterministic check: {report.agreement_rate:.1%}")
    print(f"mean faithfulness {report.mean_faithfulness:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
