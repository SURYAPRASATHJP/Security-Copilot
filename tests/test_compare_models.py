import json

from copilot.evals.compare_models import (
    CANDIDATES,
    SHIPPED,
    ModelScore,
    calls_for,
    comparison_table,
    lines_in,
    models_section,
    pick_winner,
)


def a_score(model, questions=10, correct=9, latency=1.0, cost=0.003, failed=""):
    return ModelScore(
        model=model,
        questions=questions,
        correct=correct,
        mean_latency_seconds=latency,
        cost_usd=cost,
        failed=failed,
    )


def test_every_candidate_is_a_model_the_free_tier_can_actually_serve():
    # The free tier offers no third chat model this prompt fits, so two is the honest list.
    assert len(CANDIDATES) == 2
    assert "openai/gpt-oss-120b" in CANDIDATES
    assert all(name.startswith("openai/gpt-oss") for name in CANDIDATES)


def test_accuracy_is_correct_over_asked():
    assert a_score("m", questions=10, correct=8).accuracy == 0.8


def test_a_model_that_answered_nothing_scores_zero_rather_than_dividing_by_zero():
    score = ModelScore(model="m")
    assert score.accuracy == 0.0
    assert score.cost_per_question_usd == 0.0


def test_cost_is_reported_per_question():
    assert a_score("m", questions=10, cost=0.03).cost_per_question_usd == 0.003


def test_the_most_accurate_model_wins():
    scores = [a_score("a", correct=7), a_score("b", correct=10)]
    assert pick_winner(scores).model == "b"


def test_latency_breaks_an_accuracy_tie():
    scores = [a_score("slow", correct=9, latency=3.0), a_score("fast", correct=9, latency=1.0)]
    assert pick_winner(scores).model == "fast"


def test_a_model_that_failed_cannot_win():
    scores = [a_score("broken", correct=10, failed="RateLimitError"), a_score("working", correct=5)]
    assert pick_winner(scores).model == "working"


def test_no_usable_model_has_no_winner():
    assert pick_winner([a_score("broken", failed="RateLimitError")]) is None
    assert pick_winner([]) is None


def test_the_table_names_a_failure_rather_than_hiding_it():
    table = comparison_table([a_score("broken", failed="RateLimitError")])
    assert "RateLimitError" in table


def test_the_section_names_the_model_in_use():
    scores = [a_score("openai/gpt-oss-120b", correct=10)]
    section = models_section(scores, pick_winner(scores))
    assert "is the one in use" in section
    assert "openai/gpt-oss-120b" in section


def test_a_section_with_no_winner_still_shows_the_table():
    section = models_section([a_score("broken", failed="x")], None)
    assert "## Models compared" in section
    assert "is the one in use" not in section


def test_only_calls_after_the_mark_are_counted(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    rows = [
        {"prompt_name": "answer_question", "latency_seconds": 1.0, "cost_usd": 0.001},
        {"prompt_name": "answer_question", "latency_seconds": 2.0, "cost_usd": 0.002},
        {"prompt_name": "something_else", "latency_seconds": 9.0, "cost_usd": 0.9},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert len(calls_for("answer_question", 0, log)) == 2
    assert len(calls_for("answer_question", 1, log)) == 1


def test_a_missing_log_counts_as_no_calls(tmp_path):
    assert calls_for("answer_question", 0, tmp_path / "nothing.jsonl") == []
    assert lines_in(tmp_path / "nothing.jsonl") == 0


def test_a_broken_line_in_the_log_is_skipped(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    log.write_text('{broken\n{"prompt_name": "answer_question", "cost_usd": 0.1}\n')
    assert len(calls_for("answer_question", 0, log)) == 1


def test_the_section_does_not_pass_the_winner_off_as_the_shipped_model():
    # A faster model winning on twelve questions is not the model the project ships.
    faster = a_score("openai/gpt-oss-20b", latency=0.9)
    shipped = a_score(SHIPPED, latency=1.3)
    scores = [shipped, faster]
    body = models_section(scores, pick_winner(scores))
    assert "openai/gpt-oss-20b** comes out ahead" in body
    assert f"{SHIPPED} is the one in use" in body
    assert "is the one in use, at" not in body


def test_the_section_counts_the_models_it_actually_compared():
    scores = [a_score("openai/gpt-oss-120b"), a_score("openai/gpt-oss-20b")]
    assert "put to 2 models on Groq" in models_section(scores, pick_winner(scores))
