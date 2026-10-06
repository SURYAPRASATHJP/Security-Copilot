import argparse
from collections.abc import Sequence

from pydantic import BaseModel, Field

from copilot.evals import report as eval_report
from copilot.evals.build_golden_questions import RETRIEVAL, GoldenQuestion, read_questions
from copilot.evals.retrieval_metrics import TOP_K, rank_of_first_hit, searchers
from copilot.rag.split_into_chunks import FIXED, STRUCTURED
from copilot.settings import get_settings

# The buckets a retrieval miss can fall into, decided by what the question asks for.
IDENTIFIER_MISS = "the question quotes an id that was not matched"
VERSION_MISS = "the question is about one version of a package"
DESCRIPTION_MISS = "the question asks what an advisory is about"
OTHER_MISS = "something else"


class Miss(BaseModel):
    question_id: str
    kind: str
    question: str
    bucket: str


class BucketCount(BaseModel):
    bucket: str
    misses: int = 0
    share: float = 0.0


class SetupErrors(BaseModel):
    retriever: str
    strategy: str
    questions: int = 0
    misses: int = 0
    buckets: list[BucketCount] = Field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return 1 - (self.misses / self.questions) if self.questions else 0.0


def bucket_for(question: GoldenQuestion) -> str:
    if question.kind == "fixed_version":
        return VERSION_MISS
    if question.kind == "is_affected":
        return VERSION_MISS
    if question.kind == "what_is":
        return DESCRIPTION_MISS
    return OTHER_MISS


def find_misses(questions: Sequence[GoldenQuestion], searcher, strategy: str) -> list[Miss]:  # noqa: ANN001
    """Collect every question whose right advisory never appeared in the top results."""
    misses = []
    for question in questions:
        results = list(searcher(question.question, strategy))[:TOP_K]
        if rank_of_first_hit(results, question.expected_advisory_ids) is None:
            misses.append(
                Miss(
                    question_id=question.question_id,
                    kind=question.kind,
                    question=question.question,
                    bucket=bucket_for(question),
                )
            )
    return misses


def count_buckets(misses: Sequence[Miss]) -> list[BucketCount]:
    counts: dict[str, int] = {}
    for miss in misses:
        counts[miss.bucket] = counts.get(miss.bucket, 0) + 1
    total = len(misses)
    return sorted(
        (
            BucketCount(bucket=name, misses=count, share=count / total if total else 0.0)
            for name, count in counts.items()
        ),
        key=lambda item: -item.misses,
    )


def analyse(
    questions: Sequence[GoldenQuestion], retriever: str, strategy: str
) -> tuple[SetupErrors, list[Miss]]:
    searcher = searchers()[retriever]
    misses = find_misses(questions, searcher, strategy)
    return (
        SetupErrors(
            retriever=retriever,
            strategy=strategy,
            questions=len(questions),
            misses=len(misses),
            buckets=count_buckets(misses),
        ),
        misses,
    )


def error_section(before: SetupErrors, after: SetupErrors, examples: Sequence[Miss]) -> str:
    lines = [
        "## Error analysis",
        "",
        "Every retrieval miss, bucketed by what the question was asking for. The two setups",
        "are the same retriever over the two chunk shapes, so the difference is the fix.",
        "",
        "| Setup | Questions | Misses | Hit rate |",
        "| --- | --- | --- | --- |",
        f"| {before.retriever} over {before.strategy} chunks | {before.questions} | "
        f"{before.misses} | {before.hit_rate:.3f} |",
        f"| {after.retriever} over {after.strategy} chunks | {after.questions} | "
        f"{after.misses} | {after.hit_rate:.3f} |",
        "",
        f"### The {before.strategy} chunks, by bucket",
        "",
        "| Bucket | Misses | Share |",
        "| --- | --- | --- |",
    ]
    for bucket in before.buckets:
        lines.append(f"| {bucket.bucket} | {bucket.misses} | {bucket.share:.1%} |")

    biggest = before.buckets[0] if before.buckets else None
    if biggest:
        lines.extend(
            [
                "",
                f"The biggest bucket is **{biggest.bucket}**, {biggest.misses} of "
                f"{before.misses} misses. The fix was the chunk shape rather than the",
                "retriever: a fixed-size window splits an advisory so that the half naming the",
                "package is not the half naming the version, and a question about a version",
                "then matches neither. Giving every chunk a context header and a summary card",
                f"took this setup from {before.hit_rate:.3f} to {after.hit_rate:.3f}.",
            ]
        )

    if after.buckets:
        lines.extend(["", f"### What still misses with {after.strategy} chunks", ""])
        for bucket in after.buckets:
            lines.append(f"- {bucket.bucket}: {bucket.misses}")
    else:
        lines.extend(["", f"Nothing misses with {after.strategy} chunks on this question set."])

    if examples:
        lines.extend(["", "A few of the questions that missed:", ""])
        for miss in examples[:5]:
            lines.append(f"- `{miss.question_id}`: {miss.question}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bucket the retrieval misses.")
    parser.add_argument("--retriever", default="hybrid + rerank")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    settings = get_settings()
    questions = [
        question
        for question in read_questions(settings.data_dir / "eval" / "golden_questions.jsonl")
        if RETRIEVAL in question.suites
    ]
    if args.limit:
        questions = questions[: args.limit]

    print(f"{args.retriever} over {FIXED} chunks")
    before, before_misses = analyse(questions, args.retriever, FIXED)
    print(f"  {before.misses} misses of {before.questions}")

    print(f"{args.retriever} over {STRUCTURED} chunks")
    after, after_misses = analyse(questions, args.retriever, STRUCTURED)
    print(f"  {after.misses} misses of {after.questions}")

    eval_report.write_section("errors", error_section(before, after, before_misses))
    eval_report.assemble()

    print()
    for bucket in before.buckets:
        print(f"  {bucket.bucket}: {bucket.misses} ({bucket.share:.1%})")
    print(f"\nhit rate {before.hit_rate:.3f} to {after.hit_rate:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
