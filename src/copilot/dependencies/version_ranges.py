from packaging.version import InvalidVersion, Version

from copilot.data_collection.advisory import Advisory, VersionRange


def parse_version(raw: str) -> Version | None:
    try:
        return Version(raw)
    except InvalidVersion:
        return None


def is_in_range(version: Version, window: VersionRange) -> bool:
    """Return whether the version falls inside one affected window."""
    introduced = parse_version(window.introduced) if window.introduced else None
    if introduced is not None and version < introduced:
        return False

    if window.fixed:
        fixed = parse_version(window.fixed)
        if fixed is not None:
            return version < fixed

    if window.last_affected:
        last = parse_version(window.last_affected)
        if last is not None:
            return version <= last

    # An open window with no fix and no upper bound affects everything from introduced onwards.
    return True


def is_version_affected(advisory: Advisory, raw_version: str) -> bool:
    """Decide whether one installed version is affected, using only the advisory's own bounds."""
    if raw_version in advisory.affected_versions:
        return True

    version = parse_version(raw_version)
    if version is None:
        return False
    if not advisory.ranges:
        return False
    return any(is_in_range(version, window) for window in advisory.ranges)


def an_affected_version(advisory: Advisory) -> str | None:
    """Return a version this advisory affects, preferring one OSV listed explicitly."""
    for candidate in advisory.affected_versions:
        if is_version_affected(advisory, candidate):
            return candidate
    for window in advisory.ranges:
        if window.introduced and is_version_affected(advisory, window.introduced):
            return window.introduced
        if window.last_affected and is_version_affected(advisory, window.last_affected):
            return window.last_affected
    return None


def a_safe_version(advisory: Advisory) -> str | None:
    """Return a version this advisory does not affect, which is its earliest fix."""
    fixes = [parse_version(raw) for raw in advisory.fixed_versions]
    usable = sorted(version for version in fixes if version is not None)
    for version in usable:
        if not is_version_affected(advisory, str(version)):
            return str(version)
    return None
