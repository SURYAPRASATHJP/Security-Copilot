from collections.abc import Sequence
from functools import lru_cache

import httpx
from packaging.utils import canonicalize_name
from packaging.version import Version
from pydantic import BaseModel, Field

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.dependencies.version_ranges import is_version_affected, parse_version
from copilot.settings import get_settings

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"


class SafeVersionRequest(BaseModel):
    package: str
    current_version: str | None = None
    advisory_ids: list[str] = Field(
        default_factory=list,
        description="Advisories that must be fixed. Empty means every known advisory.",
    )
    allow_prereleases: bool = False


class SafeVersionResult(BaseModel):
    package: str
    current_version: str | None = None
    safe_version: str | None = None
    advisories_considered: list[str] = Field(default_factory=list)
    advisories_still_open: list[str] = Field(default_factory=list)
    versions_available: int = 0
    reason: str = ""


@lru_cache
def advisories_by_package() -> dict[str, list[Advisory]]:
    path = get_settings().data_dir / "processed" / "advisories.jsonl"
    grouped: dict[str, list[Advisory]] = {}
    for advisory in read_advisories(path):
        grouped.setdefault(canonicalize_name(advisory.package), []).append(advisory)
    return grouped


def available_versions(package: str, client: httpx.Client) -> list[str]:
    """Return the versions PyPI actually serves, dropping yanked and fileless releases."""
    response = client.get(PYPI_JSON_URL.format(package=package))
    response.raise_for_status()
    releases = response.json().get("releases") or {}

    usable = []
    for version, files in releases.items():
        if not files or all(file.get("yanked") for file in files):
            continue
        usable.append(version)
    return usable


def sorted_versions(versions: Sequence[str], allow_prereleases: bool) -> list[Version]:
    parsed = [parse_version(version) for version in versions]
    return sorted(
        version
        for version in parsed
        if version is not None and (allow_prereleases or not version.is_prerelease)
    )


def lowest_safe_version(
    versions: Sequence[str],
    advisories: Sequence[Advisory],
    current_version: str | None = None,
    allow_prereleases: bool = False,
) -> str | None:
    """Return the lowest published version that no advisory in the list still affects."""
    current = parse_version(current_version) if current_version else None
    for version in sorted_versions(versions, allow_prereleases):
        if current is not None and version <= current:
            continue
        if not any(is_version_affected(advisory, str(version)) for advisory in advisories):
            return str(version)
    return None


def find_safe_version(request: SafeVersionRequest) -> SafeVersionResult:
    """Read only. Return the lowest version on PyPI that fixes every advisory for a package."""
    known = advisories_by_package().get(canonicalize_name(request.package), [])
    if request.advisory_ids:
        wanted = set(request.advisory_ids)
        advisories = [a for a in known if wanted.intersection(a.all_ids)]
    else:
        advisories = known

    result = SafeVersionResult(
        package=request.package,
        current_version=request.current_version,
        advisories_considered=[advisory.id for advisory in advisories],
    )

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            versions = available_versions(request.package, client)
    except httpx.HTTPError as error:
        result.reason = f"PyPI could not be read: {type(error).__name__}"
        return result

    result.versions_available = len(versions)
    if not versions:
        result.reason = "PyPI lists no usable release for this package"
        return result

    safe = lowest_safe_version(
        versions, advisories, request.current_version, request.allow_prereleases
    )
    result.safe_version = safe

    if safe is None:
        result.advisories_still_open = [advisory.id for advisory in advisories]
        result.reason = "no published version is clear of every advisory"
    elif not advisories:
        result.reason = "no advisories are on record for this package"
    else:
        result.reason = f"{safe} is the lowest published release no advisory still affects"
    return result
