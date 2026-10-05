from copilot.ml.register_best_model import (
    PRODUCTION,
    RANKING_METRIC,
    STAGING,
    TIE_BREAKER,
    Promotion,
    best_run,
    details_of,
    ranked_runs,
)


class FakeRun:
    def __init__(self, name, recall=None, f1=0.0, started=0):
        metrics = {TIE_BREAKER: f1}
        if recall is not None:
            metrics[RANKING_METRIC] = recall
        self.data = type("Data", (), {"metrics": metrics, "tags": {"mlflow.runName": name}})()
        self.info = type("Info", (), {"run_id": f"id-{name}", "start_time": started})()


class FakeClient:
    def __init__(self, runs, experiment=True):
        self.runs = runs
        self.experiment = type("Experiment", (), {"experiment_id": "1"})() if experiment else None

    def get_experiment_by_name(self, name):
        return self.experiment

    def search_runs(self, ids, max_results=100):
        return self.runs


def test_runs_are_ranked_by_recall_first():
    client = FakeClient([FakeRun("a", recall=0.80, f1=0.99), FakeRun("b", recall=0.95, f1=0.50)])
    assert [run.data.tags["mlflow.runName"] for run in ranked_runs(client)] == ["b", "a"]


def test_f1_breaks_a_recall_tie():
    client = FakeClient([FakeRun("a", recall=0.9, f1=0.70), FakeRun("b", recall=0.9, f1=0.90)])
    assert ranked_runs(client)[0].data.tags["mlflow.runName"] == "b"


def test_the_most_recent_run_wins_an_outright_tie():
    client = FakeClient(
        [
            FakeRun("older", recall=0.9, f1=0.9, started=100),
            FakeRun("newer", recall=0.9, f1=0.9, started=200),
        ]
    )
    assert ranked_runs(client)[0].data.tags["mlflow.runName"] == "newer"


def test_a_run_without_the_ranking_metric_is_ignored():
    client = FakeClient([FakeRun("unscored"), FakeRun("scored", recall=0.5)])
    assert [run.data.tags["mlflow.runName"] for run in ranked_runs(client)] == ["scored"]


def test_an_experiment_that_does_not_exist_yields_nothing():
    assert ranked_runs(FakeClient([], experiment=False)) == []
    assert best_run(FakeClient([], experiment=False)) is None


def test_no_scored_runs_means_no_best_run():
    assert best_run(FakeClient([FakeRun("unscored")])) is None


def test_the_best_run_is_the_top_of_the_ranking():
    client = FakeClient([FakeRun("a", recall=0.5), FakeRun("b", recall=0.9)])
    assert best_run(client).data.tags["mlflow.runName"] == "b"


def test_details_carry_the_scores_and_the_alias():
    details = details_of(FakeRun("distilbert", recall=0.975, f1=0.969), PRODUCTION)
    assert details.run_name == "distilbert"
    assert details.recall == 0.975
    assert details.f1 == 0.969
    assert details.alias == PRODUCTION
    assert details.promoted is False


def test_an_unpromoted_result_says_why():
    assert Promotion(reason="no model artifact").promoted is False


def test_the_two_aliases_are_distinct():
    assert STAGING != PRODUCTION
