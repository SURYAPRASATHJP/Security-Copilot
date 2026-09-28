from copilot.evals.build_golden_questions import GoldenQuestion
from copilot.evals.retrieval_metrics import (
    SetupScore,
    rank_of_first_hit,
    retrieval_table,
    score_setup,
    write_report,
)
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk


def result(advisory_id, cve_ids=()):
    return SearchResult(
        chunk=Chunk(
            chunk_id=f"{advisory_id}|p|structured|0",
            text="text",
            strategy="structured",
            advisory_id=advisory_id,
            package="requests",
            chunk_index=0,
            cve_ids=list(cve_ids),
        ),
        score=1.0,
        source="hybrid",
    )


def question(question_id, expected):
    return GoldenQuestion(
        question_id=question_id,
        question="Which version fixes it?",
        kind="fixed_version",
        expected_answer="2.31.0",
        expected_advisory_ids=expected,
    )


def test_the_rank_of_the_first_hit_is_one_based():
    results = [result("GHSA-a"), result("GHSA-b"), result("GHSA-c")]
    assert rank_of_first_hit(results, ["GHSA-c"]) == 3
    assert rank_of_first_hit(results, ["GHSA-a"]) == 1


def test_a_cve_alias_counts_as_a_hit():
    results = [result("PYSEC-2023-74", cve_ids=["CVE-2023-32681"])]
    assert rank_of_first_hit(results, ["CVE-2023-32681"]) == 1


def test_no_hit_returns_none():
    assert rank_of_first_hit([result("GHSA-a")], ["GHSA-z"]) is None


def test_an_empty_result_list_is_a_miss():
    assert rank_of_first_hit([], ["GHSA-a"]) is None


def test_a_setup_that_always_ranks_first_scores_one():
    questions = [question("q1", ["GHSA-a"]), question("q2", ["GHSA-a"])]
    score = score_setup(questions, lambda query, strategy: [result("GHSA-a")], "bm25", "structured")
    assert score.hit_rate_at_5 == 1.0
    assert score.mrr == 1.0
    assert score.questions == 2


def test_a_setup_that_never_hits_scores_zero():
    questions = [question("q1", ["GHSA-a"])]
    score = score_setup(questions, lambda query, strategy: [result("GHSA-z")], "bm25", "fixed")
    assert score.hit_rate_at_5 == 0.0
    assert score.mrr == 0.0


def test_mrr_reflects_the_rank_of_the_hit():
    questions = [question("q1", ["GHSA-c"])]
    results = [result("GHSA-a"), result("GHSA-b"), result("GHSA-c")]
    score = score_setup(questions, lambda query, strategy: results, "hybrid", "structured")
    assert score.hit_rate_at_5 == 1.0
    assert abs(score.mrr - 1 / 3) < 1e-9


def test_a_hit_below_the_cutoff_does_not_count():
    questions = [question("q1", ["GHSA-f"])]
    results = [result(f"GHSA-{letter}") for letter in "abcdef"]
    score = score_setup(questions, lambda query, strategy: results, "hybrid", "structured", k=5)
    assert score.hit_rate_at_5 == 0.0


def test_the_table_is_sorted_by_hit_rate():
    scores = [
        SetupScore(
            retriever="bm25",
            strategy="fixed",
            questions=10,
            hit_rate_at_5=0.4,
            mrr=0.3,
            seconds=1,
        ),
        SetupScore(
            retriever="hybrid",
            strategy="structured",
            questions=10,
            hit_rate_at_5=0.9,
            mrr=0.8,
            seconds=2,
        ),
    ]
    table = retrieval_table(scores)
    assert table.index("hybrid") < table.index("bm25")
    assert table.count("\n") == 3


def test_the_report_names_the_best_setup(tmp_path):
    scores = [
        SetupScore(
            retriever="bm25", strategy="fixed", questions=10, hit_rate_at_5=0.4, mrr=0.3, seconds=1
        ),
        SetupScore(
            retriever="hybrid + rerank",
            strategy="structured",
            questions=10,
            hit_rate_at_5=0.95,
            mrr=0.9,
            seconds=2,
        ),
    ]
    path = tmp_path / "eval_report.md"
    write_report(scores, path, questions=10)
    text = path.read_text()
    assert "Highest hit rate at 5: **hybrid + rerank / structured**" in text
    assert "Highest MRR, and the setup that ships: **hybrid + rerank / structured**" in text
    assert "0.950" in text
    assert "| Retriever | Chunking |" in text
