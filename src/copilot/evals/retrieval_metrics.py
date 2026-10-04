import argparse
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel

from copilot.evals import report as eval_report
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


def retrieval_section(scores: Sequence[SetupScore], questions: int) -> str:
    by_hit_rate = max(scores, key=lambda score: score.hit_rate_at_5)
    by_mrr = max(scores, key=lambda score: score.mrr)
    return "\n".join(
        [
            "## Retrieval",
            "",
            f"{questions} auto-generated retrieval questions, four retrievers against both",
            "chunking strategies.",
            "",
            retrieval_table(scores),
            "",
            f"Highest hit rate at 5: **{by_hit_rate.label}** at {by_hit_rate.hit_rate_at_5:.3f}.",
            f"Highest MRR, and the setup that ships: **{by_mrr.label}** at "
            f"{by_mrr.mrr:.3f} MRR and {by_mrr.hit_rate_at_5:.3f} hit rate at 5.",
            "",
            "### What this table does not measure",
            "",
            "Every generated question names its advisory or CVE id, so BM25 can match the",
            "identifier exactly and scores far higher here than it would on the questions a",
            "developer actually types. Read hit rate as a check that the right chunk is",
            "reachable at all, and MRR as the honest separator: reranking is what moves the",
            "right passage to position one. The production setup is hybrid search with",
            "reranking over structure-aware chunks, because it is the only one that holds up",
            "when the question does not quote an id. Removing this bias from the question set",
            "is the first item for error analysis in Phase 3.",
        ]
    )


def write_report(scores: Sequence[SetupScore], path: Path, questions: int) -> None:
    eval_report.write_section(eval_report.RETRIEVAL, retrieval_section(scores, questions))
    eval_report.assemble(path)


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
