import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field

SCORES_PATH = Path("docs/eval_scores.json")
THRESHOLDS_PATH = Path("docs/eval_thresholds.json")


class ThresholdCheck(BaseModel):
    name: str
    scored: float | None = None
    minimum: float = 0.0
    passed: bool = False
    detail: str = ""


class GateReport(BaseModel):
    checks: list[ThresholdCheck] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[ThresholdCheck]:
        return [check for check in self.checks if not check.passed]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_scores(scores: dict[str, float], path: Path | None = None) -> Path:
    """Record the scores a committed run produced, so CI has something to check."""
    path = path or SCORES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_json(path)
    existing.update({name: round(float(value), 4) for name, value in scores.items()})
    path.write_text(json.dumps(dict(sorted(existing.items())), indent=2) + "\n", encoding="utf-8")
    return path


def check(scores: dict, thresholds: dict) -> GateReport:
    """Fail when a committed score has dropped below the floor agreed for it."""
    checks = []
    for name, minimum in sorted(thresholds.items()):
        scored = scores.get(name)
        if scored is None:
            checks.append(
                ThresholdCheck(
                    name=name,
                    minimum=float(minimum),
                    passed=False,
                    detail="no score was committed for this measure",
                )
            )
            continue
        passed = float(scored) >= float(minimum)
        checks.append(
            ThresholdCheck(
                name=name,
                scored=float(scored),
                minimum=float(minimum),
                passed=passed,
                detail=f"{float(scored):.4f} against a floor of {float(minimum):.4f}",
            )
        )
    return GateReport(checks=checks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if a committed eval score has dropped.")
    parser.add_argument("--scores", type=Path, default=SCORES_PATH)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    args = parser.parse_args()

    report = check(read_json(args.scores), read_json(args.thresholds))
    for item in report.checks:
        print(f"{'ok ' if item.passed else 'BAD'} {item.name}: {item.detail}")

    if report.passed:
        print(f"\nall {len(report.checks)} eval gates passed")
        return 0

    print(f"\n{len(report.failures)} of {len(report.checks)} eval gates failed")
    print("Run make evals locally and commit docs/eval_scores.json, or justify the drop.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
