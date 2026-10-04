import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score

from copilot.ml.data_checks import read_split
from copilot.settings import get_settings

BASE_MODEL = "distilbert-base-uncased"
MODEL_NAME = "distilbert-prompt-injection"
EPOCHS = 3
BATCH_SIZE = 16
LEARNING_RATE = 5e-5
MAX_LENGTH = 256
SEED = 20260921


def metrics_from(labels: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
    }


def compute_metrics(evaluation) -> dict[str, float]:  # noqa: ANN001
    logits, labels = evaluation
    return metrics_from(labels, np.argmax(logits, axis=-1))


def as_dataset(frame: pd.DataFrame, tokenizer):  # noqa: ANN001, ANN201
    from datasets import Dataset

    dataset = Dataset.from_pandas(frame[["text", "label"]].reset_index(drop=True))
    return dataset.map(
        lambda batch: tokenizer(
            batch["text"], truncation=True, padding="max_length", max_length=MAX_LENGTH
        ),
        batched=True,
    )


def train(
    train_frame: pd.DataFrame, test_frame: pd.DataFrame, output_dir: Path, epochs: int = EPOCHS
) -> dict[str, float]:
    """Fine-tune DistilBERT on the same split the baseline used, so the numbers compare."""
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, num_labels=2)

    arguments = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=25,
        seed=SEED,
        report_to=[],
        use_cpu=True,
    )

    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=as_dataset(train_frame, tokenizer),
        eval_dataset=as_dataset(test_frame, tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()
    measured = trainer.evaluate()

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir / "model"))
    tokenizer.save_pretrained(str(output_dir / "model"))

    return {
        "precision": float(measured.get("eval_precision", 0.0)),
        "recall": float(measured.get("eval_recall", 0.0)),
        "f1": float(measured.get("eval_f1", 0.0)),
    }


def log_to_mlflow(scores: dict[str, float], epochs: int) -> str:
    import mlflow

    mlflow.set_experiment("prompt-injection-classifier")
    with mlflow.start_run(run_name=MODEL_NAME) as run:
        mlflow.log_params(
            {
                "base_model": BASE_MODEL,
                "epochs": str(epochs),
                "batch_size": str(BATCH_SIZE),
                "learning_rate": str(LEARNING_RATE),
            }
        )
        mlflow.log_metrics(scores)
        return run.info.run_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune DistilBERT on the same split.")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    train_frame, test_frame = read_split(settings.data_dir / "ml")
    output_dir = settings.data_dir / "ml" / "distilbert"

    scores = train(train_frame, test_frame, output_dir, args.epochs)
    (settings.data_dir / "ml" / "distilbert_scores.json").write_text(
        json.dumps(scores, indent=2), encoding="utf-8"
    )

    print(f"test precision: {scores['precision']:.3f}")
    print(f"test recall: {scores['recall']:.3f}")
    print(f"test F1: {scores['f1']:.3f}")
    if not args.no_mlflow:
        print(f"mlflow run: {log_to_mlflow(scores, args.epochs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
