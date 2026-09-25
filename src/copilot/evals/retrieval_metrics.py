import argparse
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from copilot.evals.build_golden_questions import RETRIEVAL, GoldenQuestion, read_questions
from copilot.rag.hybrid_search import hybrid_search
from copilot.rag.keyword_search import keyword_search
from copilot.rag.rerank_results import rerank_results
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import FIXED, STRUCTURED
from copilot.rag.vector_search import vector_search
from copilot.settings import get_settings

TOP_K = 5
RERANK_CANDIDATES = 20

BM25 = "bm25"
VECTOR = "vector"
HYBRID = "hybrid"
HYBRID_RERANK = "hybrid + rerank"

Searcher = Callable[[str, str], Sequence[SearchResult]]


class SetupScore(BaseModel):
    retriever: str
    strategy: str
    questions: int
    hit_rate_at_5: float
    mrr: float
    seconds: float

    @property
    def label(self) -> str:
        return f"{self.retriever} / {self.strategy}"


def rank_of_first_hit(results: Sequence[SearchResult], expected_ids: Sequence[str]) -> int | None:
    """Return the 1-based rank of the first result citing an expected id, or None."""
    wanted = set(expected_ids)
    for rank, result in enumerate(results, start=1):
        if wanted.intersection(result.identifiers):
            return rank
    return None


def score_setup(
    questions: Sequence[GoldenQuestion],
    searcher: Searcher,
    retriever: str,
    strategy: str,
    k: int = TOP_K,
) -> SetupScore:
    started = time.perf_counter()
    hits = 0
    reciprocal_ranks = 0.0

    for question in questions:
        results = list(searcher(question.question, strategy))[:k]
        rank = rank_of_first_hit(results, question.expected_advisory_ids)
        if rank is not None:
            hits += 1
            reciprocal_ranks += 1.0 / rank

    count = len(questions)
    return SetupScore(
        retriever=retriever,
        strategy=strategy,
        questions=count,
        hit_rate_at_5=hits / count if count else 0.0,
        mrr=reciprocal_ranks / count if count else 0.0,
        seconds=time.perf_counter() - started,
    )


def searchers() -> dict[str, Searcher]:
    """Return the four retrievers under test, each taking a query and a chunking strategy."""
    return {
        BM25: lambda query, strategy: keyword_search(query, strategy, TOP_K),
        VECTOR: lambda query, strategy: vector_search(query, strategy, TOP_K),
        HYBRID: lambda query, strategy: hybrid_search(query, strategy, TOP_K),
        HYBRID_RERANK: lambda query, strategy: rerank_results(
            query, hybrid_search(query, strategy, RERANK_CANDIDATES), TOP_K
        ),
    }


def score_every_setup(questions: Sequence[GoldenQuestion]) -> list[SetupScore]:
    scores = []
    for retriever, searcher in searchers().items():
        for strategy in (FIXED, STRUCTURED):
            score = score_setup(questions, searcher, retriever, strategy)
            print(
                f"{score.label:28} hit@5 {score.hit_rate_at_5:.3f}  "
                f"mrr {score.mrr:.3f}  {score.seconds:.0f}s"
            )
            scores.append(score)
    return scores


def retrieval_table(scores: Sequence[SetupScore]) -> str:
    ordered = sorted(scores, key=lambda score: -score.hit_rate_at_5)
    lines = [
        "| Retriever | Chunking | Questions | Hit rate at 5 | MRR | Seconds |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for score in ordered:
        lines.append(
            f"| {score.retriever} | {score.strategy} | {score.questions} | "
            f"{score.hit_rate_at_5:.3f} | {score.mrr:.3f} | {score.seconds:.0f} |"
        )
    return "\n".join(lines)


def write_report(scores: Sequence[SetupScore], path: Path, questions: int) -> None:
    best = max(scores, key=lambda score: score.hit_rate_at_5)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Evaluation report",
                "",
                "Every number here comes from `make evals`. The golden set is generated from the",
                "advisory corpus itself, so each answer is known without anyone labelling it.",
                "",
                "## Retrieval",
                "",
                f"{questions} auto-generated retrieval questions, four retrievers against both",
                "chunking strategies.",
                "",
                retrieval_table(scores),
                "",
                f"Best setup: **{best.label}** at {best.hit_rate_at_5:.3f} hit rate at 5 and "
                f"{best.mrr:.3f} MRR.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score every retrieval setup.")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N questions")
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if RETRIEVAL in question.suites
    ]
    if args.limit:
        questions = questions[: args.limit]

    scores = score_every_setup(questions)
    write_report(scores, Path("docs/eval_report.md"), len(questions))
    print(f"\nreport written to docs/eval_report.md for {len(questions)} questions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
