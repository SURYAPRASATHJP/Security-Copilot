from copilot.evals.answer_metrics import (
    AnswerOutcome,
    answer_table,
    append_to_report,
    is_correct,
    says_yes,
    score_one,
    summarise,
)
from copilot.evals.build_golden_questions import GoldenQuestion
from copilot.rag.answer_with_citations import REFUSAL_TEXT, CitedAnswer


def outcome(kind, answerable, refused, correct, wrong=()):
    return AnswerOutcome(
        question_id=f"{kind}:{refused}:{correct}",
        kind=kind,
        answerable=answerable,
        refused=refused,
        correct=correct,
        wrong_citations=list(wrong),
    )


def question(kind, expected, ids=("GHSA-a",), answerable=True):
    return GoldenQuestion(
        question_id=f"{kind}:1",
        question="a question",
        kind=kind,
        expected_answer=expected,
        expected_advisory_ids=list(ids),
        answerable=answerable,
    )


def test_a_plain_yes_is_read_as_yes():
    assert says_yes("Yes, that version is affected.") is True


def test_a_plain_no_is_read_as_no():
    assert says_yes("No, 2.31.0 is not affected.") is False


def test_a_sentence_with_neither_word_is_unreadable():
    assert says_yes("Upgrade when you can.") is None


def test_a_sentence_claiming_both_is_unreadable():
    assert says_yes("Yes and no, it depends.") is None


def test_a_fixed_version_answer_must_contain_the_version():
    good = CitedAnswer(answer="Upgrade to 2.31.0.")
    bad = CitedAnswer(answer="Upgrade to the latest release.")
    assert is_correct(question("fixed_version", "2.31.0"), good) is True
    assert is_correct(question("fixed_version", "2.31.0"), bad) is False


def test_a_wrong_version_is_not_counted_as_correct():
    answer = CitedAnswer(answer="Upgrade to 2.30.0.")
    assert is_correct(question("fixed_version", "2.31.0"), answer) is False


def test_an_is_affected_answer_must_agree_with_the_version_comparison():
    yes = CitedAnswer(answer="Yes, that version is affected.")
    assert is_correct(question("is_affected", "yes"), yes) is True
    assert is_correct(question("is_affected", "no"), yes) is False


def test_a_what_is_answer_must_cite_the_right_advisory():
    right = CitedAnswer(answer="It leaks a header.", citations=["GHSA-a"])
    wrong = CitedAnswer(answer="It leaks a header.", citations=["GHSA-z"])
    assert is_correct(question("what_is", "summary"), right) is True
    assert is_correct(question("what_is", "summary"), wrong) is False


def test_a_refusal_is_never_a_correct_answer_to_an_answerable_question():
    assert (
        is_correct(question("fixed_version", "2.31.0"), CitedAnswer(answer=REFUSAL_TEXT)) is False
    )


def test_a_refusal_is_the_correct_outcome_for_an_unanswerable_question():
    unanswerable = question("unanswerable", "refuse", ids=(), answerable=False)
    outcome = score_one(unanswerable, CitedAnswer(answer=REFUSAL_TEXT))
    assert outcome.correct is True
    assert outcome.refused is True


def test_answering_an_unanswerable_question_is_wrong():
    unanswerable = question("unanswerable", "refuse", ids=(), answerable=False)
    outcome = score_one(unanswerable, CitedAnswer(answer="Upgrade to 9.9.9."))
    assert outcome.correct is False


def test_a_wrong_citation_is_recorded_on_the_outcome():
    answer = CitedAnswer(answer="Upgrade to 2.31.0.", unverified_citations=["GHSA-fake"])
    assert score_one(question("fixed_version", "2.31.0"), answer).wrong_citations == ["GHSA-fake"]


def test_the_summary_counts_each_measure_separately():
    outcomes = [
        AnswerOutcome(
            question_id="1", kind="fixed_version", answerable=True, refused=False, correct=True
        ),
        AnswerOutcome(
            question_id="2", kind="fixed_version", answerable=True, refused=True, correct=False
        ),
        AnswerOutcome(
            question_id="3",
            kind="what_is",
            answerable=True,
            refused=False,
            correct=False,
            wrong_citations=["GHSA-fake"],
        ),
        AnswerOutcome(
            question_id="4", kind="unanswerable", answerable=False, refused=True, correct=True
        ),
        AnswerOutcome(
            question_id="5", kind="unanswerable", answerable=False, refused=False, correct=False
        ),
    ]
    score = summarise(outcomes, seconds=1.0)
    assert score.questions == 5
    assert score.answerable == 3
    assert score.unanswerable == 2
    assert abs(score.answer_accuracy - 1 / 3) < 1e-9
    assert score.refusal_accuracy == 0.5
    assert score.wrong_citation_rate == 0.2
    assert abs(score.over_refusal_rate - 1 / 3) < 1e-9


def test_an_empty_run_does_not_divide_by_zero():
    score = summarise([], seconds=0.0)
    assert score.answer_accuracy == 0.0
    assert score.refusal_accuracy == 0.0
    assert score.wrong_citation_rate == 0.0


def test_the_table_names_every_measure():
    score = summarise([], seconds=0.0)
    table = answer_table(score)
    for label in (
        "Answer accuracy",
        "Refusal accuracy",
        "Wrong citation rate",
        "Over-refusal rate",
    ):
        assert label in table


def test_the_answers_section_is_written_with_its_numbers(tmp_path, monkeypatch):
    from copilot.evals import report as eval_report

    monkeypatch.setattr(eval_report, "sections_dir", lambda: tmp_path / "sections")
    outcomes = [outcome("fixed_version", answerable=True, refused=False, correct=True)]
    append_to_report(summarise(outcomes, 1.0), tmp_path / "eval_report.md", outcomes)

    body = eval_report.read_section(eval_report.ANSWERS)
    assert "## Answers" in body
    assert "| fixed_version | 1 | 1 |" in body


def test_re_running_the_answer_eval_replaces_its_section(tmp_path, monkeypatch):
    from copilot.evals import report as eval_report

    monkeypatch.setattr(eval_report, "sections_dir", lambda: tmp_path / "sections")
    report_path = tmp_path / "eval_report.md"
    for _ in range(3):
        outcomes = [outcome("fixed_version", answerable=True, refused=False, correct=True)]
        append_to_report(summarise(outcomes, 1.0), report_path, outcomes)

    assert report_path.read_text().count("## Answers") == 1
