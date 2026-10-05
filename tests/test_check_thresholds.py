import json
from pathlib import Path

from copilot.evals.check_thresholds import (
    SCORES_PATH,
    THRESHOLDS_PATH,
    check,
    read_json,
    write_scores,
)

THRESHOLDS = {"answer_accuracy": 0.9, "retrieval_mrr": 0.92}


def test_a_score_above_its_floor_passes():
    report = check({"answer_accuracy": 0.95, "retrieval_mrr": 0.97}, THRESHOLDS)
    assert report.passed is True
    assert report.failures == []


def test_a_score_exactly_on_its_floor_passes():
    assert check({"answer_accuracy": 0.9, "retrieval_mrr": 0.92}, THRESHOLDS).passed is True


def test_a_score_below_its_floor_fails_and_says_by_how_much():
    report = check({"answer_accuracy": 0.80, "retrieval_mrr": 0.97}, THRESHOLDS)
    assert report.passed is False
    assert len(report.failures) == 1
    assert "0.8000 against a floor of 0.9000" in report.failures[0].detail


def test_a_missing_score_fails_rather_than_passing_quietly():
    report = check({"retrieval_mrr": 0.97}, THRESHOLDS)
    assert report.passed is False
    assert "no score was committed" in report.failures[0].detail


def test_every_threshold_is_checked_not_just_the_first():
    report = check({}, THRESHOLDS)
    assert len(report.failures) == 2


def test_an_extra_score_with_no_threshold_is_ignored():
    scores = {"answer_accuracy": 0.95, "retrieval_mrr": 0.97, "something_else": 0.0}
    assert check(scores, THRESHOLDS).passed is True


def test_scores_are_written_and_read_back(tmp_path):
    path = write_scores({"answer_accuracy": 0.9512}, tmp_path / "eval_scores.json")
    assert read_json(path) == {"answer_accuracy": 0.9512}


def test_writing_one_score_leaves_the_others_alone(tmp_path):
    path = tmp_path / "eval_scores.json"
    write_scores({"answer_accuracy": 0.95}, path)
    write_scores({"retrieval_mrr": 0.97}, path)
    assert read_json(path) == {"answer_accuracy": 0.95, "retrieval_mrr": 0.97}


def test_writing_the_same_score_again_replaces_it(tmp_path):
    path = tmp_path / "eval_scores.json"
    write_scores({"answer_accuracy": 0.95}, path)
    write_scores({"answer_accuracy": 0.80}, path)
    assert read_json(path) == {"answer_accuracy": 0.80}


def test_a_missing_file_reads_as_empty(tmp_path):
    assert read_json(tmp_path / "nothing.json") == {}


def test_the_committed_thresholds_file_is_valid_and_demanding():
    thresholds = read_json(Path(THRESHOLDS_PATH))
    assert thresholds
    assert thresholds["agent_safety"] == 1.0
    assert all(0.0 < float(value) <= 1.0 for value in thresholds.values())


def test_the_committed_scores_are_json_if_they_exist():
    path = Path(SCORES_PATH)
    if path.exists():
        assert isinstance(json.loads(path.read_text()), dict)
