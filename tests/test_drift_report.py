import pandas as pd

from copilot.ml.build_training_data import BENIGN, INJECTION
from copilot.ml.drift_report import (
    DriftSummary,
    drift_verdict,
    simulate_a_week,
    with_features,
)


class FakeRun:
    def __init__(self, payload):
        self.payload = payload

    def dict(self):
        return self.payload


def drifted_count(count, share):
    return FakeRun(
        {
            "metrics": [
                {
                    "metric_name": "DriftedColumnsCount(drift_share=0.5)",
                    "value": {"count": count, "share": share},
                }
            ]
        }
    )


def test_a_simulated_week_is_mostly_real_questions():
    week = simulate_a_week(400)
    assert len(week) == 400
    assert 0.02 < week["label"].mean() < 0.2


def test_the_same_seed_gives_the_same_week():
    assert list(simulate_a_week(50, seed=3)["text"]) == list(simulate_a_week(50, seed=3)["text"])


def test_a_simulated_week_contains_both_labels():
    labels = set(simulate_a_week(400)["label"])
    assert labels == {BENIGN, INJECTION}


def test_length_features_are_added():
    frame = pd.DataFrame({"text": ["one two three"], "label": [BENIGN]})
    featured = with_features(frame)
    assert featured["characters"][0] == 13
    assert featured["words"][0] == 3


def test_adding_features_does_not_change_the_original():
    frame = pd.DataFrame({"text": ["abc"], "label": [BENIGN]})
    with_features(frame)
    assert list(frame.columns) == ["text", "label"]


def test_drift_is_read_from_the_run_not_guessed():
    detected, drifted, checked = drift_verdict(drifted_count(4.0, 1.0))
    assert detected is True
    assert drifted == 4
    assert checked == 4


def test_no_drifted_columns_means_no_drift():
    detected, drifted, checked = drift_verdict(drifted_count(0.0, 0.0))
    assert detected is False
    assert drifted == 0


def test_a_partial_drift_reports_both_numbers():
    detected, drifted, checked = drift_verdict(drifted_count(2.0, 0.5))
    assert detected is True
    assert (drifted, checked) == (2, 4)


def test_a_run_without_the_metric_reports_nothing_rather_than_guessing():
    assert drift_verdict(FakeRun({"metrics": []})) == (False, 0, 0)


def test_a_run_that_cannot_be_read_does_not_raise():
    class Broken:
        def dict(self):
            raise RuntimeError("no")

    assert drift_verdict(Broken()) == (False, 0, 0)


def test_the_summary_names_how_many_columns_drifted():
    summary = DriftSummary(
        drift_detected=True,
        drifted_columns=4,
        columns_checked=4,
        reference_injection_share=0.347,
        live_injection_share=0.088,
        reference_mean_length=101,
        live_mean_length=59,
    )
    assert "drift detected in 4 of 4 columns" in summary.summary
    assert "34.7%" in summary.summary


def test_a_clean_summary_says_no_drift():
    assert "no drift detected" in DriftSummary().summary
