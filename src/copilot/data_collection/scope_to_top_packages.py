import argparse
import json
from collections.abc import Iterable
from pathlib import Path

import httpx
from packaging.utils import canonicalize_name

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.load_osv_advisories import load_osv_folder
from copilot.settings import get_settings

TOP_PACKAGES_URL = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json"
DEFAULT_PACKAGE_LIMIT = 300


def top_package_names(payload: dict, limit: int) -> list[str]:
    """Return the most-downloaded project names from the top-pypi-packages payload."""
    rows = sorted(payload["rows"], key=lambda row: row["download_count"], reverse=True)
    return [row["project"] for row in rows[:limit]]


def fetch_top_packages(limit: int = DEFAULT_PACKAGE_LIMIT, url: str = TOP_PACKAGES_URL) -> list[str]:
    response = httpx.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    return top_package_names(response.json(), limit)


def scope_to_packages(advisories: Iterable[Advisory], packages: Iterable[str]) -> list[Advisory]:
    """Keep only advisories whose package is in the wanted set, comparing normalised names."""
    wanted = {canonicalize_name(name) for name in packages}
    return [a for a in advisories if canonicalize_name(a.package) in wanted]


def write_advisories(advisories: Iterable[Advisory], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for advisory in advisories:
            handle.write(advisory.model_dump_json() + "\n")
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Scope the advisory corpus to popular packages.")
    parser.add_argument("--limit", type=int, default=DEFAULT_PACKAGE_LIMIT)
    args = parser.parse_args()

    settings = get_settings()
    processed = settings.data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    packages = fetch_top_packages(args.limit)
    (processed / "top_packages.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")

    report = load_osv_folder(settings.data_dir / "raw" / "osv_pypi")
    scoped = scope_to_packages(report.advisories, packages)
    written = write_advisories(scoped, processed / "scoped_advisories.jsonl")

    covered = {canonicalize_name(a.package) for a in scoped}
    cves = {cve for a in scoped for cve in a.cve_ids}

    print(f"top packages tracked: {len(packages)}")
    print(f"advisories in scope: {written} of {len(report.advisories)}")
    print(f"packages with at least one advisory: {len(covered)}")
    print(f"distinct CVEs to enrich: {len(cves)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
