import argparse
from pathlib import Path

import matplotlib
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, learning_curve
from sklearn.pipeline import Pipeline

from copilot.ml.data_checks import read_split
from copilot.settings import get_settings

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

MODEL_NAME = "tfidf-logistic-regression"
FOLDS = 5
SEED = 20260921
LEARNING_CURVE_PATH = Path("docs/learning_curve.png")


class ClassifierScores(BaseModel):
    model: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    cross_validated_f1: float = 0.0
    cross_validated_spread: float = 0.0
    train_rows: int = 0
    test_rows: int = 0
    report: str = ""
    parameters: dict[str, str] = Field(default_factory=dict)


def build_pipeline() -> Pipeline:
    """Words and short word sequences, which is enough to separate an order from a question."""
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            ("model", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]
    )


def cross_validate(pipeline: Pipeline, texts: pd.Series, labels: pd.Series) -> tuple[float, float]:
    folds = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    scores = cross_val_score(pipeline, texts, labels, cv=folds, scoring="f1")
    return float(scores.mean()), float(scores.std())


def save_learning_curve(
    pipeline: Pipeline, texts: pd.Series, labels: pd.Series, path: Path
) -> Path:
    """Plot training against validation score, which is where bias and variance show up."""
    folds = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    sizes, train_scores, validation_scores = learning_curve(
        pipeline, texts, labels, cv=folds, scoring="f1", train_sizes=[0.2, 0.4, 0.6, 0.8, 1.0]
    )

    figure, axes = plt.subplots(figsize=(7, 4.5))
    axes.plot(sizes, train_scores.mean(axis=1), marker="o", label="training")
    axes.plot(sizes, validation_scores.mean(axis=1), marker="o", label="validation")
    axes.fill_between(
        sizes,
        validation_scores.mean(axis=1) - validation_scores.std(axis=1),
        validation_scores.mean(axis=1) + validation_scores.std(axis=1),
        alpha=0.15,
    )
    axes.set_xlabel("training rows")
    axes.set_ylabel("F1")
    axes.set_title("Learning curve, TF-IDF and logistic regression")
    axes.legend()
    figure.tight_layout()

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)
    plt.close(figure)
    return path


def score(pipeline: Pipeline, texts: pd.Series, labels: pd.Series) -> dict[str, float]:
    predicted = pipeline.predict(texts)
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "report": classification_report(labels, predicted, zero_division=0),
    }


def train(train_frame: pd.DataFrame, test_frame: pd.DataFrame) -> tuple[Pipeline, ClassifierScores]:
    pipeline = build_pipeline()
    mean_f1, spread = cross_validate(pipeline, train_frame["text"], train_frame["label"])
    pipeline.fit(train_frame["text"], train_frame["label"])
    measured = score(pipeline, test_frame["text"], test_frame["label"])

    scores = ClassifierScores(
        model=MODEL_NAME,
        precision=measured["precision"],
        recall=measured["recall"],
        f1=measured["f1"],
        cross_validated_f1=mean_f1,
        cross_validated_spread=spread,
        train_rows=len(train_frame),
        test_rows=len(test_frame),
        report=measured["report"],
        parameters={"ngram_range": "1 to 2", "min_df": "2", "class_weight": "balanced"},
    )
    return pipeline, scores


def log_to_mlflow(pipeline: Pipeline, scores: ClassifierScores) -> str:
    """Record the run so the three classifiers can be compared later on equal terms."""
    import mlflow
    import mlflow.sklearn

    mlflow.set_experiment("prompt-injection-classifier")
    with mlflow.start_run(run_name=MODEL_NAME) as run:
        mlflow.log_params(scores.parameters)
        mlflow.log_metrics(
            {
                "precision": scores.precision,
                "recall": scores.recall,
                "f1": scores.f1,
                "cross_validated_f1": scores.cross_validated_f1,
            }
        )
        mlflow.sklearn.log_model(pipeline, name=MODEL_NAME)
        return run.info.run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the TF-IDF baseline classifier.")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    train_frame, test_frame = read_split(settings.data_dir / "ml")
    pipeline, scores = train(train_frame, test_frame)

    save_learning_curve(
        build_pipeline(), train_frame["text"], train_frame["label"], LEARNING_CURVE_PATH
    )
    output = settings.data_dir / "ml" / "baseline_scores.json"
    output.write_text(scores.model_dump_json(indent=2), encoding="utf-8")

    print(
        f"cross validated F1: {scores.cross_validated_f1:.3f} "
        f"(+/- {scores.cross_validated_spread:.3f})"
    )
    print(f"test precision: {scores.precision:.3f}")
    print(f"test recall: {scores.recall:.3f}")
    print(f"test F1: {scores.f1:.3f}")
    print(f"\n{scores.report}")
    print(f"learning curve: {LEARNING_CURVE_PATH}")

    if not args.no_mlflow:
        print(f"mlflow run: {log_to_mlflow(pipeline, scores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
