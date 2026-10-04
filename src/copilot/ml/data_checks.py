from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors
from pydantic import BaseModel, Field

from copilot.ml.build_training_data import BENIGN, GOLDEN, INJECTION, PUBLIC, RED_TEAM
from copilot.settings import get_settings

KNOWN_SOURCES = (PUBLIC, RED_TEAM, GOLDEN)
MINIMUM_MINORITY_SHARE = 0.15

TRAINING_SCHEMA = pa.DataFrameSchema(
    {
        "text": pa.Column(str, checks=pa.Check.str_length(min_value=1), nullable=False),
        "label": pa.Column(int, checks=pa.Check.isin([BENIGN, INJECTION]), nullable=False),
        "source": pa.Column(str, checks=pa.Check.isin(list(KNOWN_SOURCES)), nullable=False),
    },
    strict=True,
    unique=["text"],
)


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class DataReport(BaseModel):
    checks: list[CheckResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]

    def summary(self) -> str:
        passed = sum(1 for check in self.checks if check.passed)
        return f"{passed} of {len(self.checks)} data checks passed"


def check_schema(frame: pd.DataFrame, name: str) -> CheckResult:
    try:
        TRAINING_SCHEMA.validate(frame, lazy=True)
    except SchemaErrors as errors:
        return CheckResult(name=f"{name} schema", passed=False, detail=str(errors)[:300])
    return CheckResult(name=f"{name} schema", passed=True, detail=f"{len(frame)} rows")


def check_no_duplicates(frame: pd.DataFrame, name: str) -> CheckResult:
    repeated = int(frame["text"].duplicated().sum())
    return CheckResult(
        name=f"{name} has no repeated text",
        passed=repeated == 0,
        detail=f"{repeated} repeated rows",
    )


def check_label_balance(frame: pd.DataFrame, name: str) -> CheckResult:
    """A split where one label is rare teaches the model to guess the common one."""
    if frame.empty:
        return CheckResult(name=f"{name} label balance", passed=False, detail="no rows")
    share = frame["label"].value_counts(normalize=True)
    minority = float(share.min())
    return CheckResult(
        name=f"{name} label balance",
        passed=minority >= MINIMUM_MINORITY_SHARE,
        detail=f"smallest class is {minority:.1%} of the split",
    )


def check_no_leakage(train: pd.DataFrame, test: pd.DataFrame) -> CheckResult:
    """A row in both halves makes the test score a measure of memory, not learning."""
    shared = set(train["text"]).intersection(test["text"])
    return CheckResult(
        name="no text appears in both train and test",
        passed=not shared,
        detail=f"{len(shared)} rows appear in both",
    )


def run_checks(train: pd.DataFrame, test: pd.DataFrame) -> DataReport:
    return DataReport(
        checks=[
            check_schema(train, "train"),
            check_schema(test, "test"),
            check_no_duplicates(train, "train"),
            check_no_duplicates(test, "test"),
            check_label_balance(train, "train"),
            check_label_balance(test, "test"),
            check_no_leakage(train, test),
        ]
    )


def read_split(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_csv(folder / "train.csv"), pd.read_csv(folder / "test.csv")


def main() -> int:
    train, test = read_split(get_settings().data_dir / "ml")
    report = run_checks(train, test)

    for check in report.checks:
        print(f"{'ok ' if check.passed else 'BAD'} {check.name}: {check.detail}")
    print()
    print(report.summary())
    print(f"train {len(train)} rows, test {len(test)} rows")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
