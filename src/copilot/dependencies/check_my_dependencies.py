import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.dependencies.read_requirements_file import (
    ParsedRequirement,
    RequirementsFile,
    read_requirements_file,
)
from copilot.settings import get_settings

OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_ADVISORY_URL = "https://osv.dev/vulnerability/"

# OSV accepts a large batch, but 100 keeps one slow request from losing the whole scan.
QUERY_BATCH_SIZE = 100


class Finding(BaseModel):
    package: str
    canonical_name: str
    installed_version: str | None
    advisory_id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    fixed_version: str | None = None
    severity: str | None = None
    cvss_score: float | None = None
    epss_probability: float | None = None
    known_exploited: bool = False

    @property
    def advisory_url(self) -> str:
        return f"{OSV_ADVISORY_URL}{self.advisory_id}"


class DependencyReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    packages_checked: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def affected_packages(self) -> list[str]:
        return sorted({finding.canonical_name for finding in self.findings})


def lowest_fixed_version(advisory: Advisory) -> str | None:
    """Return the earliest version that fixes this advisory, ignoring unparsable ones."""
    parsed = []
    for raw in advisory.fixed_versions:
        try:
            parsed.append(Version(raw))
        except InvalidVersion:
            continue
    return str(min(parsed)) if parsed else None


def index_local_advisories(advisories: Iterable[Advisory]) -> dict[tuple[str, str], Advisory]:
    """Index advisories by package and by every id they answer to, including CVE aliases."""
    index: dict[tuple[str, str], Advisory] = {}
    for advisory in advisories:
        package = canonicalize_name(advisory.package)
        for identifier in advisory.all_ids:
            index[(package, identifier)] = advisory
    return index


def build_queries(requirements: Sequence[ParsedRequirement]) -> list[dict]:
    queries = []
    for requirement in requirements:
        query: dict = {"package": {"name": requirement.name, "ecosystem": "PyPI"}}
        if requirement.pinned_version:
            query["version"] = requirement.pinned_version
        queries.append(query)
    return queries


def advisory_ids_from_batch(payload: dict) -> list[list[str]]:
    return [
        [vuln["id"] for vuln in (result or {}).get("vulns") or []]
        for result in payload.get("results", [])
    ]


def query_osv(queries: Sequence[dict], client: httpx.Client) -> list[list[str]]:
    ids: list[list[str]] = []
    for start in range(0, len(queries), QUERY_BATCH_SIZE):
        batch = list(queries[start : start + QUERY_BATCH_SIZE])
        response = client.post(OSV_QUERYBATCH_URL, json={"queries": batch})
        response.raise_for_status()
        ids.extend(advisory_ids_from_batch(response.json()))
    return ids


def risk_key(finding: Finding) -> tuple:
    """Order findings by what a developer should fix first."""
    return (
        0 if finding.known_exploited else 1,
        -(finding.epss_probability or 0.0),
        -(finding.cvss_score or 0.0),
        finding.canonical_name,
        finding.advisory_id,
    )


def _duplicate_key(finding: Finding) -> tuple:
    cves = tuple(sorted(alias for alias in finding.aliases if alias.startswith("CVE-")))
    return (finding.canonical_name, cves or (finding.advisory_id,))


def _record_preference(finding: Finding) -> tuple:
    # The GHSA record carries the readable summary, so it wins over the PYSEC mirror.
    return (0 if finding.advisory_id.startswith("GHSA-") else 1, finding.advisory_id)


def deduplicate_findings(findings: Sequence[Finding]) -> list[Finding]:
    """Collapse advisories that describe the same CVE for the same package into one finding."""
    groups: dict[tuple, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(_duplicate_key(finding), []).append(finding)

    merged = []
    for group in groups.values():
        best, *rest = sorted(group, key=_record_preference)
        extra = [other.advisory_id for other in rest if other.advisory_id not in best.aliases]
        merged.append(best.model_copy(update={"aliases": [*best.aliases, *extra]}))
    return sorted(merged, key=risk_key)


def build_findings(
    requirements: Sequence[ParsedRequirement],
    advisory_ids: Sequence[Sequence[str]],
    index: dict[tuple[str, str], Advisory],
) -> list[Finding]:
    findings = []
    for requirement, ids in zip(requirements, advisory_ids, strict=False):
        for advisory_id in ids:
            advisory = index.get((requirement.canonical_name, advisory_id))
            findings.append(
                Finding(
                    package=requirement.name,
                    canonical_name=requirement.canonical_name,
                    installed_version=requirement.pinned_version,
                    advisory_id=advisory_id,
                    aliases=advisory.aliases if advisory else [],
                    summary=advisory.summary if advisory else "",
                    fixed_version=lowest_fixed_version(advisory) if advisory else None,
                    severity=advisory.severity if advisory else None,
                    cvss_score=advisory.cvss_score if advisory else None,
                    epss_probability=advisory.epss_probability if advisory else None,
                    known_exploited=advisory.known_exploited if advisory else False,
                )
            )
    return deduplicate_findings(findings)


def check_requirements(
    parsed: RequirementsFile,
    index: dict[tuple[str, str], Advisory],
    client: httpx.Client,
) -> DependencyReport:
    """Ask OSV which pinned versions are affected, then attach the local advisory record."""
    queries = build_queries(parsed.requirements)
    advisory_ids = query_osv(queries, client) if queries else []
    return DependencyReport(
        findings=build_findings(parsed.requirements, advisory_ids, index),
        packages_checked=len(parsed.requirements),
        warnings=list(parsed.warnings),
    )


def check_requirements_file(path: Path) -> DependencyReport:
    settings = get_settings()
    index = index_local_advisories(
        read_advisories(settings.data_dir / "processed" / "advisories.jsonl")
    )
    parsed = read_requirements_file(path)
    with httpx.Client(timeout=60.0) as client:
        return check_requirements(parsed, index, client)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a requirements file against OSV.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    report = check_requirements_file(args.path)

    print(f"packages checked: {report.packages_checked}")
    print(f"packages affected: {len(report.affected_packages)}")
    print(f"findings: {len(report.findings)}\n")
    for finding in report.findings:
        kev = "KEV " if finding.known_exploited else ""
        epss = f"epss {finding.epss_probability:.4f} " if finding.epss_probability else ""
        cvss = f"cvss {finding.cvss_score} " if finding.cvss_score else ""
        fixed = f"fixed in {finding.fixed_version}" if finding.fixed_version else "no fix listed"
        version = finding.installed_version or "unpinned"
        print(f"{finding.package}=={version}  {finding.advisory_id}  {kev}{epss}{cvss}{fixed}")
    for warning in report.warnings:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
