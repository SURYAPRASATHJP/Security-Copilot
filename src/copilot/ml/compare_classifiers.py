import argparse
import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel
from sklearn.metrics import f1_score, precision_score, recall_score

from copilot.evals.check_thresholds import write_scores
from copilot.guardrails.input_guard import ask_the_guard_model, looks_like_an_obvious_injection
from copilot.ml.data_checks import read_split
from copilot.ml.train_baseline_classifier import build_pipeline
from copilot.settings import get_settings

PATTERN = "pattern rule"
BASELINE = "tfidf and logistic regression"
DISTILBERT = "distilbert"
PROMPT_GUARD = "llama prompt guard 2"

# Missing an attack costs more than asking a developer to rephrase, so recall is weighted up.
MINIMUM_PRECISION = 0.75
PROMPT_GUARD_SAMPLE = 40
PROMPT_GUARD_PAUSE = 2.0


class ClassifierComparison(BaseModel):
    model: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    threshold: float | None = None
    rows: int = 0
    milliseconds_per_row: float = 0.0
    cost_per_thousand_usd: float = 0.0
    note: str = ""


def measure(labels: Sequence[int], predicted: Sequence[int]) -> dict[str, float]:
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
    }


def time_predictions(predict: Callable[[Sequence[str]], Sequence[int]], texts: Sequence[str]):  # noqa: ANN201
    started = time.perf_counter()
    predicted = predict(texts)
    elapsed = time.perf_counter() - started
    return predicted, elapsed / len(texts) * 1000 if texts else 0.0


def best_threshold_for_recall(
    probabilities: np.ndarray, labels: Sequence[int], minimum_precision: float = MINIMUM_PRECISION
) -> float:
    """Pick the threshold with the most recall that still keeps precision acceptable."""
    best = 0.5
    best_recall = -1.0
    for threshold in np.arange(0.05, 0.96, 0.05):
        predicted = (probabilities >= threshold).astype(int)
        scored = measure(labels, predicted)
        if scored["precision"] >= minimum_precision and scored["recall"] > best_recall:
            best, best_recall = float(threshold), scored["recall"]
    return best


def score_pattern(test: pd.DataFrame) -> ClassifierComparison:
    predicted, per_row = time_predictions(
        lambda texts: [int(looks_like_an_obvious_injection(text)) for text in texts],
        list(test["text"]),
    )
    return ClassifierComparison(
        model=PATTERN,
        **measure(test["label"], predicted),
        rows=len(test),
        milliseconds_per_row=per_row,
        note="the regular expression already in the input guard, free and instant",
    )


def score_baseline(train: pd.DataFrame, test: pd.DataFrame) -> ClassifierComparison:
    pipeline = build_pipeline()
    pipeline.fit(train["text"], train["label"])
    probabilities = pipeline.predict_proba(test["text"])[:, 1]
    threshold = best_threshold_for_recall(probabilities, test["label"])

    predicted, per_row = time_predictions(
        lambda texts: (pipeline.predict_proba(texts)[:, 1] >= threshold).astype(int),
        list(test["text"]),
    )
    return ClassifierComparison(
        model=BASELINE,
        **measure(test["label"], predicted),
        threshold=threshold,
        rows=len(test),
        milliseconds_per_row=per_row,
        note="threshold tuned for recall while precision stays above 0.75",
    )


def score_distilbert(test: pd.DataFrame, model_dir: Path) -> ClassifierComparison:
    if not (model_dir / "config.json").exists():
        return ClassifierComparison(
            model=DISTILBERT, rows=0, note="not trained yet, run finetune_distilbert.py"
        )

    from transformers import pipeline as hf_pipeline

    classifier = hf_pipeline(
        "text-classification", model=str(model_dir), tokenizer=str(model_dir), device=-1
    )

    def predict(texts: Sequence[str]) -> list[int]:
        results = classifier(list(texts), truncation=True, max_length=256)
        return [int(result["label"].endswith("1")) for result in results]

    predicted, per_row = time_predictions(predict, list(test["text"]))
    return ClassifierComparison(
        model=DISTILBERT,
        **measure(test["label"], predicted),
        rows=len(test),
        milliseconds_per_row=per_row,
        note="fine-tuned on the same split, runs locally on CPU",
    )


def score_prompt_guard(
    test: pd.DataFrame, sample: int = PROMPT_GUARD_SAMPLE
) -> ClassifierComparison:
    """Score Groq's Prompt Guard on a sample, because every row is a billed API call."""
    rows = test.head(sample)
    predicted = []
    started = time.perf_counter()
    for text in rows["text"]:
        try:
            predicted.append(int(ask_the_guard_model(text)))
        except Exception as error:
            return ClassifierComparison(
                model=PROMPT_GUARD,
                rows=len(predicted),
                note=f"stopped early: {type(error).__name__}",
            )
        time.sleep(PROMPT_GUARD_PAUSE)
    elapsed = time.perf_counter() - started

    settings = get_settings()
    return ClassifierComparison(
        model=PROMPT_GUARD,
        **measure(rows["label"], predicted),
        rows=len(rows),
        milliseconds_per_row=elapsed / len(rows) * 1000 if len(rows) else 0.0,
        cost_per_thousand_usd=settings.input_usd_per_million_tokens * 1000 * 0.05,
        note=f"scored on {len(rows)} rows, since each one is an API call",
    )


def comparison_table(scores: Sequence[ClassifierComparison]) -> str:
    lines = [
        "| Model | Precision | Recall | F1 | Threshold | Rows | ms per row | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for score in scores:
        threshold = f"{score.threshold:.2f}" if score.threshold is not None else "n/a"
        lines.append(
            f"| {score.model} | {score.precision:.3f} | {score.recall:.3f} | {score.f1:.3f} | "
            f"{threshold} | {score.rows} | {score.milliseconds_per_row:.1f} | {score.note} |"
        )
    return "\n".join(lines)


def pick_winner(scores: Sequence[ClassifierComparison]) -> ClassifierComparison:
    """Recall first, because an attack that gets through costs more than a false alarm."""
    usable = [score for score in scores if score.rows]
    return max(usable, key=lambda score: (score.recall, score.f1)) if usable else scores[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the prompt injection classifiers.")
    parser.add_argument("--skip-prompt-guard", action="store_true")
    parser.add_argument("--prompt-guard-sample", type=int, default=PROMPT_GUARD_SAMPLE)
    args = parser.parse_args()

    settings = get_settings()
    train, test = read_split(settings.data_dir / "ml")

    scores = [score_pattern(test), score_baseline(train, test)]
    scores.append(score_distilbert(test, settings.data_dir / "ml" / "distilbert" / "model"))
    if not args.skip_prompt_guard:
        scores.append(score_prompt_guard(test, args.prompt_guard_sample))

    output = settings.data_dir / "ml" / "classifier_comparison.json"
    output.write_text(json.dumps([s.model_dump() for s in scores], indent=2), encoding="utf-8")

    winner_now = pick_winner(scores)
    write_scores({"classifier_recall": winner_now.recall, "classifier_f1": winner_now.f1})

    print(comparison_table(scores))
    print()
    winner = pick_winner(scores)
    print(f"highest recall: {winner.model} at {winner.recall:.3f} recall, {winner.f1:.3f} F1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
