import random

from copilot.data_collection.advisory import Advisory, VersionRange
from copilot.dependencies.version_ranges import is_version_affected
from copilot.evals.build_golden_questions import (
    ANSWER,
    REFUSAL,
    RETRIEVAL,
    assign_suites,
    build_golden_questions,
    fake_cve_ids,
    fake_package_names,
    fixed_version_questions,
    is_affected_questions,
    read_questions,
    unanswerable_questions,
    what_is_questions,
    write_questions,
)


def advisory(number: int, fixed: str | None = "2.0.0", summary: str = "A real problem") -> Advisory:
    window = VersionRange(introduced="1.0.0", fixed=fixed)
    return Advisory(
        id=f"GHSA-{number:04d}",
        package=f"package{number}",
        aliases=[f"CVE-2023-{number:05d}"],
        ranges=[window],
        fixed_versions=[fixed] if fixed else [],
        affected_versions=["1.5.0"],
        summary=summary,
    )


ADVISORIES = [advisory(n) for n in range(10)]


def test_a_fixed_version_question_has_the_real_fix_as_its_answer():
    questions = fixed_version_questions(ADVISORIES, 3)
    assert len(questions) == 3
    assert questions[0].expected_answer == "2.0.0"
    assert questions[0].question == "Which version of package0 fixes GHSA-0000?"


def test_an_advisory_with_no_fix_produces_no_fixed_version_question():
    assert fixed_version_questions([advisory(1, fixed=None)], 5) == []


def test_every_expected_advisory_id_includes_the_cve_alias():
    question = fixed_version_questions(ADVISORIES, 1)[0]
    assert "GHSA-0000" in question.expected_advisory_ids
    assert "CVE-2023-00000" in question.expected_advisory_ids


def test_is_affected_questions_alternate_between_yes_and_no():
    questions = is_affected_questions(ADVISORIES, 6)
    assert [q.expected_answer for q in questions] == ["yes", "no", "yes", "no", "yes", "no"]


def test_every_is_affected_answer_agrees_with_the_version_logic():
    lookup = {a.id: a for a in ADVISORIES}
    for question in is_affected_questions(ADVISORIES, 6):
        advisory_id, version = (
            question.question_id.split(":")[1],
            question.question_id.split(":")[3],
        )
        expected = "yes" if is_version_affected(lookup[advisory_id], version) else "no"
        assert question.expected_answer == expected


def test_a_what_is_question_uses_the_summary_as_the_answer():
    question = what_is_questions(ADVISORIES, 1)[0]
    assert question.question == "What is CVE-2023-00000 about?"
    assert question.expected_answer == "A real problem"


def test_an_advisory_with_no_summary_produces_no_what_is_question():
    assert what_is_questions([advisory(1, summary="")], 5) == []


def test_fake_package_names_avoid_the_real_ones():
    rng = random.Random(1)
    taken = {"flask-quantum-auth"}
    names = fake_package_names(5, taken, rng)
    assert len(set(names)) == 5
    assert "flask-quantum-auth" not in names


def test_fake_cve_ids_avoid_the_real_ones():
    rng = random.Random(1)
    ids = fake_cve_ids(5, {"CVE-2099-10000"}, rng)
    assert len(set(ids)) == 5
    assert "CVE-2099-10000" not in ids
    assert all(identifier.startswith("CVE-2099-") for identifier in ids)


def test_unanswerable_questions_expect_a_refusal_and_sit_in_the_answer_suite_only():
    questions = unanswerable_questions(8, {"requests"}, {"GHSA-1"}, ["requests"], random.Random(2))
    assert len(questions) == 8
    assert all(q.expected_answer == REFUSAL for q in questions)
    assert all(q.answerable is False for q in questions)
    assert all(q.suites == [ANSWER] for q in questions)
    assert all(q.expected_advisory_ids == [] for q in questions)


def test_unanswerable_questions_use_all_four_shapes():
    questions = unanswerable_questions(8, set(), set(), ["requests"], random.Random(3))
    assert {q.question.split()[0] for q in questions} == {"Which", "Is", "What", "Does"}


def test_every_answerable_question_is_in_the_retrieval_suite():
    questions = fixed_version_questions(ADVISORIES, 6)
    assign_suites(questions, 2)
    assert all(RETRIEVAL in q.suites for q in questions)
    assert sum(1 for q in questions if ANSWER in q.suites) == 2


def test_the_full_set_hits_the_planned_shape():
    many = [advisory(n) for n in range(300)]
    questions = build_golden_questions(many)
    retrieval = [q for q in questions if RETRIEVAL in q.suites]
    answer = [q for q in questions if ANSWER in q.suites]
    assert len(retrieval) == 200
    assert len(answer) == 50
    assert sum(1 for q in questions if not q.answerable) == 20


def test_the_same_seed_gives_the_same_questions():
    many = [advisory(n) for n in range(300)]
    first = [q.question for q in build_golden_questions(many, seed=7)]
    second = [q.question for q in build_golden_questions(many, seed=7)]
    assert first == second


def test_a_different_seed_changes_the_set():
    many = [advisory(n) for n in range(300)]
    first = [q.question for q in build_golden_questions(many, seed=7)]
    second = [q.question for q in build_golden_questions(many, seed=8)]
    assert first != second


def test_questions_round_trip_through_disk(tmp_path):
    questions = build_golden_questions([advisory(n) for n in range(300)])
    path = tmp_path / "golden.jsonl"
    assert write_questions(questions, path) == len(questions)
    assert [q.question_id for q in read_questions(path)] == [q.question_id for q in questions]
