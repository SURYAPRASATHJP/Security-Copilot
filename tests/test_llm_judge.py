import json

from copilot import llm_client
from copilot.evals.build_golden_questions import GoldenQuestion
from copilot.evals.llm_judge import (
    JUDGE_SCHEMA,
    Judgement,
    JudgeOutcome,
    format_passages,
    judge_answer,
    judge_one,
    judge_section,
    summarise,
)
from copilot.rag.answer_with_citations import REFUSAL_TEXT, CitedAnswer
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk

PASSAGE = SearchResult(
    chunk=Chunk(
        chunk_id="GHSA-a|requests|structured|0",
        text="Advisory GHSA-a for package requests: fixed in 2.31.0",
        strategy="structured",
        advisory_id="GHSA-a",
        package="requests",
        chunk_index=0,
    ),
    score=5.0,
    source="reranked",
)


def a_question(kind="fixed_version", expected="2.31.0", answerable=True):
    return GoldenQuestion(
        question_id=f"{kind}:1",
        question="Which version fixes it?",
        kind=kind,
        expected_answer=expected,
        expected_advisory_ids=["GHSA-a"],
        answerable=answerable,
    )


def canned(monkeypatch, faithfulness=1.0, correctness=1.0, reason="looks right"):
    payload = json.dumps(
        {"faithfulness": faithfulness, "correctness": correctness, "reason": reason}
    )
    monkeypatch.setattr(llm_client, "ask_llm", lambda *a, **k: payload)


def test_passages_are_labelled_with_their_advisory():
    assert "[GHSA-a]" in format_passages([PASSAGE])


def test_no_passages_is_said_plainly():
    assert format_passages([]) == "No passages were retrieved."


def test_a_judgement_is_read_from_the_reply(monkeypatch):
    canned(monkeypatch, 0.9, 0.8, "mostly supported")
    judged = judge_answer("q", "a", [PASSAGE], "2.31.0")
    assert judged.faithfulness == 0.9
    assert judged.correctness == 0.8
    assert judged.reason == "mostly supported"


def test_an_unreadable_reply_scores_zero_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(llm_client, "ask_llm", lambda *a, **k: "not json")
    judged = judge_answer("q", "a", [PASSAGE], "2.31.0")
    assert judged.faithfulness == 0.0
    assert "did not return a readable score" in judged.reason


def test_the_judge_is_asked_in_schema_mode(monkeypatch):
    sent = {}

    def fake(messages, json_schema=None, **kwargs):
        sent["schema"] = json_schema
        return json.dumps({"faithfulness": 1, "correctness": 1, "reason": "ok"})

    monkeypatch.setattr(llm_client, "ask_llm", fake)
    judge_answer("q", "a", [PASSAGE], "2.31.0")
    assert sent["schema"] == JUDGE_SCHEMA


def test_a_low_correctness_score_reads_as_wrong():
    assert Judgement(correctness=0.2).says_correct is False
    assert Judgement(correctness=0.5).says_correct is True


def test_the_judge_agreeing_with_the_code_is_recorded(monkeypatch):
    canned(monkeypatch, 1.0, 1.0)
    answer = CitedAnswer(answer="Upgrade to 2.31.0.", passages=[PASSAGE])
    outcome = judge_one(a_question(), answer)
    assert outcome.code_says_correct is True
    assert outcome.agreed is True


def test_the_judge_disagreeing_with_the_code_is_recorded(monkeypatch):
    canned(monkeypatch, 1.0, 0.0, "the version is wrong")
    answer = CitedAnswer(answer="Upgrade to 2.31.0.", passages=[PASSAGE])
    outcome = judge_one(a_question(), answer)
    assert outcome.code_says_correct is True
    assert outcome.agreed is False


def test_an_unanswerable_question_is_graded_on_whether_it_refused(monkeypatch):
    canned(monkeypatch, 1.0, 1.0)
    answer = CitedAnswer(answer=REFUSAL_TEXT)
    outcome = judge_one(
        a_question(kind="unanswerable", expected="refuse", answerable=False), answer
    )
    assert outcome.code_says_correct is True
    assert outcome.agreed is True


def test_the_summary_averages_the_scores_and_counts_agreement():
    outcomes = [
        JudgeOutcome(
            question_id="1",
            kind="fixed_version",
            judgement=Judgement(faithfulness=1.0, correctness=1.0),
            code_says_correct=True,
            agreed=True,
        ),
        JudgeOutcome(
            question_id="2",
            kind="what_is",
            judgement=Judgement(faithfulness=0.5, correctness=0.0),
            code_says_correct=True,
            agreed=False,
        ),
    ]
    report = summarise(outcomes, 1.0)
    assert report.judged == 2
    assert report.mean_faithfulness == 0.75
    assert report.agreement_rate == 0.5


def test_an_empty_run_does_not_divide_by_zero():
    assert summarise([], 0.0).agreement_rate == 0.0


def test_the_section_leads_with_agreement_not_the_score():
    report = summarise([], 0.0)
    section = judge_section(report, [])
    assert "Agreement with the deterministic check" in section
    assert "whether the judge can be trusted" in section


def test_a_disagreement_is_named_in_the_section():
    outcome = JudgeOutcome(
        question_id="fixed_version:9",
        kind="fixed_version",
        judgement=Judgement(correctness=0.0, reason="no passage supports that version"),
        code_says_correct=True,
        agreed=False,
    )
    section = judge_section(summarise([outcome], 1.0), [outcome])
    assert "fixed_version:9" in section
    assert "judge says wrong, code says right" in section
