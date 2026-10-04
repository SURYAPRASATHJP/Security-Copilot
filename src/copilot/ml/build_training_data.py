import argparse
import random
from pathlib import Path

import pandas as pd

from copilot.evals.build_golden_questions import read_questions
from copilot.settings import get_settings
from red_team.build_attacks import read_attacks

PUBLIC_DATASET = "deepset/prompt-injections"
INJECTION = 1
BENIGN = 0
TEST_FRACTION = 0.25
SEED = 20260921

PUBLIC = "public"
RED_TEAM = "red team"
GOLDEN = "golden set"


def from_red_team() -> pd.DataFrame:
    """Our own attacks, every one of them an injection by construction."""
    attacks = read_attacks()
    return pd.DataFrame(
        {
            "text": [attack.prompt for attack in attacks],
            "label": INJECTION,
            "source": RED_TEAM,
        }
    )


def from_golden_questions() -> pd.DataFrame:
    """Real questions a developer would ask, which the classifier must not flag."""
    path = get_settings().data_dir / "eval" / "golden_questions.jsonl"
    questions = read_questions(path)
    return pd.DataFrame(
        {
            "text": [question.question for question in questions],
            "label": BENIGN,
            "source": GOLDEN,
        }
    )


def from_public_dataset(name: str = PUBLIC_DATASET) -> pd.DataFrame:
    from datasets import load_dataset

    loaded = load_dataset(name)
    frames = []
    for split in loaded:
        frame = loaded[split].to_pandas()
        frames.append(frame[["text", "label"]])
    combined = pd.concat(frames, ignore_index=True)
    combined["source"] = PUBLIC
    return combined


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Join the sources, drop exact repeats, and keep the order stable."""
    combined = pd.concat(frames, ignore_index=True)
    combined["text"] = combined["text"].astype(str).str.strip()
    combined = combined[combined["text"] != ""]
    combined["label"] = combined["label"].astype(int)
    return combined.drop_duplicates(subset="text").reset_index(drop=True)


def split(frame: pd.DataFrame, test_fraction: float = TEST_FRACTION, seed: int = SEED) -> tuple:
    """Split so both labels appear in both halves and no text crosses the line."""
    rng = random.Random(seed)
    train_rows = []
    test_rows = []
    for label in sorted(frame["label"].unique()):
        rows = frame[frame["label"] == label].index.tolist()
        rng.shuffle(rows)
        cut = int(len(rows) * test_fraction)
        test_rows.extend(rows[:cut])
        train_rows.extend(rows[cut:])
    return (
        frame.loc[sorted(train_rows)].reset_index(drop=True),
        frame.loc[sorted(test_rows)].reset_index(drop=True),
    )


def write_split(train: pd.DataFrame, test: pd.DataFrame, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    train_path = folder / "train.csv"
    test_path = folder / "test.csv"
    train.to_csv(train_path, index=False)
    test.to_csv(test_path, index=False)
    return train_path, test_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the prompt injection training set.")
    parser.add_argument("--no-public", action="store_true", help="skip the Hugging Face dataset")
    args = parser.parse_args()

    frames = [from_red_team(), from_golden_questions()]
    if not args.no_public:
        frames.append(from_public_dataset())

    combined = combine(frames)
    train, test = split(combined)
    folder = get_settings().data_dir / "ml"
    train_path, test_path = write_split(train, test, folder)

    print(f"rows: {len(combined)}")
    for source, count in combined["source"].value_counts().items():
        print(f"  {source}: {count}")
    print(
        f"injections: {int(combined['label'].sum())}, benign: {int((1 - combined['label']).sum())}"
    )
    print(f"train: {len(train)} to {train_path}")
    print(f"test: {len(test)} to {test_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
