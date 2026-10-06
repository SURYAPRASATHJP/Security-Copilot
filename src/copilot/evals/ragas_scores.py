import argparse
import time
from collections.abc import Sequence

from pydantic import BaseModel, Field

from copilot.evals import report as eval_report
from copilot.evals.answer_metrics import SECONDS_BETWEEN_CALLS
from copilot.evals.build_golden_questions import ANSWER, GoldenQuestion, read_questions
from copilot.rag.answer_with_citations import CitedAnswer, answer_question
from copilot.settings import get_settings, require_groq_key

DEFAULT_QUESTIONS = 30
BATCH_SIZE = 5

FAITHFULNESS = "faithfulness"
RELEVANCY = "answer relevancy"
CONTEXT_PRECISION = "context precision"
CONTEXT_RECALL = "context recall"


class RagasScores(BaseModel):
    questions: int = 0
    scores: dict[str, float] = Field(default_factory=dict)
    seconds: float = 0.0
    failed: str = ""


class AnsweredQuestion(BaseModel):
    question: str
    answer: str
    contexts: list[str] = Field(default_factory=list)
    reference: str = ""


def collect_answers(questions: Sequence[GoldenQuestion], pause: float) -> list[AnsweredQuestion]:
    """Answer each question once, keeping the passages that were actually used."""
    collected = []
    for index, question in enumerate(questions, start=1):
        answer: CitedAnswer = answer_question(question.question)
        collected.append(
            AnsweredQuestion(
                question=question.question,
                answer=answer.answer,
                contexts=[passage.chunk.text for passage in answer.passages],
                reference=question.expected_answer,
            )
        )
        print(f"  answered {index}/{len(questions)}")
        if index < len(questions):
            time.sleep(pause)
    return collected


def groq_judge():  # noqa: ANN201
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    settings = require_groq_key()
    return LangchainLLMWrapper(
        ChatOpenAI(
            model=settings.model_name,
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            temperature=0,
            max_retries=6,
        )
    )


def local_embeddings():  # noqa: ANN201
    """The same local model the index uses, so no embedding API is needed."""
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=get_settings().embedding_model_name)
    )


def build_dataset(answered: Sequence[AnsweredQuestion]):  # noqa: ANN201
    from ragas import EvaluationDataset, SingleTurnSample

    return EvaluationDataset(
        samples=[
            SingleTurnSample(
                user_input=item.question,
                response=item.answer,
                retrieved_contexts=item.contexts or ["no passage was retrieved"],
                reference=item.reference,
            )
            for item in answered
        ]
    )


def score_with_ragas(
    answered: Sequence[AnsweredQuestion], batch_size: int = BATCH_SIZE
) -> RagasScores:
    """Run the four RAGAS metrics in small batches, because of the per-minute token limit."""
    from ragas import evaluate
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    started = time.perf_counter()
    judge = groq_judge()
    embeddings = local_embeddings()
    metrics = [
        Faithfulness(llm=judge),
        ResponseRelevancy(llm=judge, embeddings=embeddings),
        LLMContextPrecisionWithReference(llm=judge),
        LLMContextRecall(llm=judge),
    ]

    try:
        result = evaluate(
            dataset=build_dataset(answered),
            metrics=metrics,
            llm=judge,
            embeddings=embeddings,
            batch_size=batch_size,
        )
    except Exception as error:
        return RagasScores(
            questions=len(answered),
            seconds=time.perf_counter() - started,
            failed=f"{type(error).__name__}: {error}",
        )

    scores = {
        name: float(value) for name, value in dict(result).items() if isinstance(value, int | float)
    }
    return RagasScores(
        questions=len(answered), scores=scores, seconds=time.perf_counter() - started
    )


def ragas_section(result: RagasScores, own_faithfulness: float | None = None) -> str:
    lines = [
        "## RAGAS",
        "",
        "RAGAS scores the same answers with its own prompts, using Groq as the judge and the",
        "local bge embeddings. It is here as a second opinion written by someone else, which",
        "is the only reason a second opinion is worth having.",
        "",
    ]
    if result.failed:
        lines.extend([f"The run did not finish: {result.failed}", ""])
        return "\n".join(lines)

    lines.extend(["| Metric | Score |", "| --- | --- |"])
    for name, value in sorted(result.scores.items()):
        lines.append(f"| {name} | {value:.3f} |")
    lines.append("")
    lines.append(f"Measured over {result.questions} questions in {result.seconds:.0f} seconds.")

    faithfulness = result.scores.get("faithfulness")
    if faithfulness is not None and own_faithfulness is not None:
        lines.extend(
            [
                "",
                f"My own judge scored faithfulness at {own_faithfulness:.3f} against RAGAS's "
                f"{faithfulness:.3f}. Where the two disagree, neither is the truth: the",
                "disagreement is the signal that this is a measure worth looking at by hand.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the answers with RAGAS.")
    parser.add_argument("--limit", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument("--sleep", type=float, default=SECONDS_BETWEEN_CALLS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if ANSWER in question.suites and question.answerable
    ][: args.limit or None]

    print(f"answering {len(questions)} questions")
    answered = collect_answers(questions, args.sleep)

    print("scoring with RAGAS")
    result = score_with_ragas(answered, args.batch_size)

    eval_report.write_section("ragas", ragas_section(result))
    eval_report.assemble()

    if result.failed:
        print(f"RAGAS did not finish: {result.failed}")
        return 1
    for name, value in sorted(result.scores.items()):
        print(f"  {name}: {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
