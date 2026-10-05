import argparse

from pydantic import BaseModel

EXPERIMENT = "prompt-injection-classifier"
REGISTERED_NAME = "prompt-injection-guard"
STAGING = "staging"
PRODUCTION = "production"

# Recall decides, because a missed injection costs more than a developer rephrasing.
RANKING_METRIC = "recall"
TIE_BREAKER = "f1"


class Promotion(BaseModel):
    run_id: str = ""
    run_name: str = ""
    version: str = ""
    recall: float = 0.0
    f1: float = 0.0
    alias: str = ""
    promoted: bool = False
    reason: str = ""


def ranked_runs(client, experiment_name: str = EXPERIMENT) -> list:  # noqa: ANN001
    """Return every scored run, best first: highest recall, then F1, then most recent."""
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        return []

    runs = client.search_runs([experiment.experiment_id], max_results=200)
    scored = [run for run in runs if RANKING_METRIC in run.data.metrics]
    return sorted(
        scored,
        key=lambda run: (
            run.data.metrics.get(RANKING_METRIC, 0.0),
            run.data.metrics.get(TIE_BREAKER, 0.0),
            run.info.start_time or 0,
        ),
        reverse=True,
    )


def best_run(client, experiment_name: str = EXPERIMENT):  # noqa: ANN001, ANN201
    ranked = ranked_runs(client, experiment_name)
    return ranked[0] if ranked else None


def details_of(run, alias: str) -> Promotion:  # noqa: ANN001
    return Promotion(
        run_id=run.info.run_id,
        run_name=run.data.tags.get("mlflow.runName", ""),
        recall=run.data.metrics.get(RANKING_METRIC, 0.0),
        f1=run.data.metrics.get(TIE_BREAKER, 0.0),
        alias=alias,
    )


def promote(experiment_name: str = EXPERIMENT, alias: str = PRODUCTION) -> Promotion:
    """Register the best run that carries a model, and give it the alias the app loads by."""
    import mlflow
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    client = MlflowClient()
    ranked = ranked_runs(client, experiment_name)
    if not ranked:
        return Promotion(reason=f"no runs with a {RANKING_METRIC} metric in {experiment_name}")

    skipped = 0
    for run in ranked:
        details = details_of(run, alias)
        try:
            # A run can score well and still have no model to serve, so try the next one.
            version = mlflow.register_model(f"runs:/{run.info.run_id}/model", REGISTERED_NAME)
        except MlflowException:
            skipped += 1
            continue

        client.set_registered_model_alias(REGISTERED_NAME, STAGING, version.version)
        client.set_registered_model_alias(REGISTERED_NAME, alias, version.version)
        note = f"highest {RANKING_METRIC} of the logged runs"
        if skipped:
            note += f", after skipping {skipped} that logged no model"
        return details.model_copy(
            update={"version": str(version.version), "promoted": True, "reason": note}
        )

    return details_of(ranked[0], alias).model_copy(
        update={"reason": "no run in the experiment carries a model that can be registered"}
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote the best classifier run.")
    parser.add_argument("--alias", default=PRODUCTION)
    args = parser.parse_args()

    result = promote(alias=args.alias)
    if not result.run_id:
        print(result.reason)
        return 1

    print(f"best run: {result.run_name or result.run_id}")
    print(f"  recall {result.recall:.3f}, f1 {result.f1:.3f}")
    if result.promoted:
        print(f"registered as {REGISTERED_NAME} version {result.version}")
        print(f"aliases: {STAGING} and {result.alias}")
    else:
        print(result.reason)
    return 0 if result.promoted else 1


if __name__ == "__main__":
    raise SystemExit(main())
