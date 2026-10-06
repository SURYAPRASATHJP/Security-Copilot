from copilot.evals.build_golden_questions import GoldenQuestion
from copilot.evals.error_analysis import (
    DESCRIPTION_MISS,
    OTHER_MISS,
    VERSION_MISS,
    Miss,
    SetupErrors,
    bucket_for,
    count_buckets,
    error_section,
    find_misses,
)
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk


def a_question(kind, question_id="q1"):
    return GoldenQuestion(
        question_id=question_id,
        question="a question",
        kind=kind,
        expected_answer="x",
        expected_advisory_ids=["GHSA-wanted"],
    )


def a_result(advisory_id):
    return SearchResult(
        chunk=Chunk(
            chunk_id=f"{advisory_id}|p|structured|0",
            text="text",
            strategy="structured",
            advisory_id=advisory_id,
            package="requests",
            chunk_index=0,
        ),
        score=1.0,
        source="hybrid",
    )


def test_a_version_question_lands_in_the_version_bucket():
    assert bucket_for(a_question("fixed_version")) == VERSION_MISS
    assert bucket_for(a_question("is_affected")) == VERSION_MISS


def test_a_description_question_lands_in_the_description_bucket():
    assert bucket_for(a_question("what_is")) == DESCRIPTION_MISS


def test_an_unknown_kind_lands_in_the_other_bucket():
    assert bucket_for(a_question("something_new")) == OTHER_MISS


def test_a_question_whose_advisory_was_found_is_not_a_miss():
    found = find_misses(
        [a_question("what_is")], lambda q, s: [a_result("GHSA-wanted")], "structured"
    )
    assert found == []


def test_a_question_whose_advisory_never_appeared_is_a_miss():
    missed = find_misses(
        [a_question("what_is")], lambda q, s: [a_result("GHSA-other")], "structured"
    )
    assert len(missed) == 1
    assert missed[0].bucket == DESCRIPTION_MISS


def test_an_empty_result_list_is_a_miss():
    assert len(find_misses([a_question("what_is")], lambda q, s: [], "structured")) == 1


def test_buckets_are_counted_largest_first():
    misses = [
        Miss(question_id="1", kind="what_is", question="q", bucket=DESCRIPTION_MISS),
        Miss(question_id="2", kind="what_is", question="q", bucket=DESCRIPTION_MISS),
        Miss(question_id="3", kind="fixed_version", question="q", bucket=VERSION_MISS),
    ]
    counts = count_buckets(misses)
    assert counts[0].bucket == DESCRIPTION_MISS
    assert counts[0].misses == 2
    assert abs(counts[0].share - 2 / 3) < 1e-9


def test_no_misses_means_no_buckets():
    assert count_buckets([]) == []


def test_the_hit_rate_is_derived_from_the_misses():
    assert SetupErrors(retriever="r", strategy="s", questions=200, misses=96).hit_rate == 0.52
    assert SetupErrors(retriever="r", strategy="s").hit_rate == 0.0


def test_the_section_shows_the_before_and_the_after():
    before = SetupErrors(
        retriever="hybrid + rerank",
        strategy="fixed",
        questions=200,
        misses=96,
        buckets=count_buckets(
            [
                Miss(question_id=str(n), kind="what_is", question="q", bucket=DESCRIPTION_MISS)
                for n in range(96)
            ]
        ),
    )
    after = SetupErrors(retriever="hybrid + rerank", strategy="structured", questions=200, misses=1)
    section = error_section(before, after, [])
    assert "0.520" in section
    assert "0.995" in section
    assert "biggest bucket" in section
    assert DESCRIPTION_MISS in section


def test_a_setup_that_misses_nothing_says_so():
    before = SetupErrors(retriever="r", strategy="fixed", questions=10, misses=1)
    after = SetupErrors(retriever="r", strategy="structured", questions=10, misses=0)
    assert "Nothing misses" in error_section(before, after, [])


def test_example_misses_are_quoted():
    before = SetupErrors(retriever="r", strategy="fixed", questions=10, misses=1)
    after = SetupErrors(retriever="r", strategy="structured", questions=10, misses=0)
    examples = [
        Miss(
            question_id="what_is:7",
            kind="what_is",
            question="What is CVE-1 about?",
            bucket=DESCRIPTION_MISS,
        )
    ]
    section = error_section(before, after, examples)
    assert "what_is:7" in section
    assert "What is CVE-1 about?" in section
