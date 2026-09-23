import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from copilot.data_collection.advisory import Advisory, advisories_from_osv
from copilot.settings import get_settings


@dataclass
class LoadReport:
    files_read: int = 0
    advisories: list[Advisory] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        return len(self.failures) / self.files_read if self.files_read else 0.0

    @property
    def packages(self) -> set[str]:
        return {advisory.package for advisory in self.advisories}


def load_one_file(path: Path) -> list[Advisory]:
    record = json.loads(path.read_text(encoding="utf-8"))
    return advisories_from_osv(record)


def load_osv_folder(folder: Path) -> LoadReport:
    """Parse every advisory file in the folder, collecting failures rather than raising."""
    report = LoadReport()
    for path in sorted(folder.glob("*.json")):
        report.files_read += 1
        try:
            report.advisories.extend(load_one_file(path))
        except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as error:
            report.failures.append({"file": path.name, "error": f"{type(error).__name__}: {error}"})
    return report


def main() -> int:
    raw = get_settings().data_dir / "raw"
    report = load_osv_folder(raw / "osv_pypi")

    failure_log = raw / "osv_load_failures.jsonl"
    with failure_log.open("w", encoding="utf-8") as handle:
        for failure in report.failures:
            handle.write(json.dumps(failure) + "\n")

    print(f"files read: {report.files_read}")
    print(f"advisories built: {len(report.advisories)}")
    print(f"distinct packages: {len(report.packages)}")
    print(f"failures: {len(report.failures)} ({report.failure_rate:.3%})")
    if report.failures:
        print(f"failures logged to {failure_log}")
    return 0 if report.failure_rate < 0.01 else 1


if __name__ == "__main__":
    raise SystemExit(main())
