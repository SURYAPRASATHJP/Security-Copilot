from datetime import datetime
from typing import Any

from packaging.utils import canonicalize_name
from pydantic import BaseModel, Field

CVE_PREFIX = "CVE-"
GHSA_PREFIX = "GHSA-"


class VersionRange(BaseModel):
    introduced: str | None = None
    fixed: str | None = None
    last_affected: str | None = None


class Advisory(BaseModel):
    id: str
    package: str
    aliases: list[str] = Field(default_factory=list)
    ranges: list[VersionRange] = Field(default_factory=list)
    fixed_versions: list[str] = Field(default_factory=list)
    affected_versions: list[str] = Field(default_factory=list)
    summary: str = ""
    details: str = ""
    severity: str | None = None
    cvss_vector: str | None = None
    cvss_score: float | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    epss_probability: float | None = None
    known_exploited: bool = False
    references: list[str] = Field(default_factory=list)
    published: datetime | None = None
    modified: datetime | None = None
    withdrawn: datetime | None = None

    @property
    def cve_ids(self) -> list[str]:
        return [alias for alias in self.aliases if alias.startswith(CVE_PREFIX)]

    @property
    def ghsa_ids(self) -> list[str]:
        ids = [alias for alias in self.aliases if alias.startswith(GHSA_PREFIX)]
        return [self.id, *ids] if self.id.startswith(GHSA_PREFIX) else ids

    @property
    def all_ids(self) -> list[str]:
        return list(dict.fromkeys([self.id, *self.aliases]))


def _version_ranges(affected: dict[str, Any]) -> list[VersionRange]:
    ranges: list[VersionRange] = []
    for raw_range in affected.get("ranges", []):
        current = VersionRange()
        for event in raw_range.get("events", []):
            if "introduced" in event:
                # A new introduced event starts a fresh window, so close the previous one.
                if current.introduced is not None:
                    ranges.append(current)
                    current = VersionRange()
                current.introduced = event["introduced"]
            if "fixed" in event:
                current.fixed = event["fixed"]
            if "last_affected" in event:
                current.last_affected = event["last_affected"]
        if current.introduced or current.fixed or current.last_affected:
            ranges.append(current)
    return ranges


def _cvss_vector(record: dict[str, Any]) -> str | None:
    for entry in record.get("severity", []):
        score = entry.get("score")
        if isinstance(score, str) and score.startswith("CVSS:"):
            return score
    return None


def advisories_from_osv(record: dict[str, Any]) -> list[Advisory]:
    """Return one Advisory per PyPI package the OSV record affects."""
    severity_word = (record.get("database_specific") or {}).get("severity")
    references = [ref["url"] for ref in record.get("references", []) if ref.get("url")]

    # One record can list the same package in several affected blocks, one per version window.
    by_package: dict[str, dict[str, Any]] = {}
    for affected in record.get("affected", []):
        package = affected.get("package") or {}
        name = package.get("name")
        if package.get("ecosystem") != "PyPI" or not name:
            continue
        group = by_package.setdefault(
            canonicalize_name(name), {"name": name, "ranges": [], "versions": []}
        )
        group["ranges"].extend(_version_ranges(affected))
        group["versions"].extend(affected.get("versions", []))

    advisories = []
    for group in by_package.values():
        ranges = list(
            {(r.introduced, r.fixed, r.last_affected): r for r in group["ranges"]}.values()
        )
        advisories.append(
            Advisory(
                id=record["id"],
                package=group["name"],
                aliases=list(record.get("aliases", [])),
                ranges=ranges,
                fixed_versions=list(dict.fromkeys(r.fixed for r in ranges if r.fixed)),
                affected_versions=list(dict.fromkeys(group["versions"])),
                summary=record.get("summary", "") or "",
                details=record.get("details", "") or "",
                severity=severity_word,
                cvss_vector=_cvss_vector(record),
                references=references,
                published=record.get("published"),
                modified=record.get("modified"),
                withdrawn=record.get("withdrawn"),
            )
        )
    return advisories
