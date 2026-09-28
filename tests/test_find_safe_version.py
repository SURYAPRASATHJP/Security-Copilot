import httpx

from copilot.agents.tools import find_safe_version as module
from copilot.agents.tools.find_safe_version import (
    SafeVersionRequest,
    available_versions,
    find_safe_version,
    lowest_safe_version,
    sorted_versions,
)
from copilot.data_collection.advisory import Advisory, VersionRange

REQUESTS = Advisory(
    id="GHSA-j8r2",
    package="requests",
    aliases=["CVE-2023-32681"],
    ranges=[VersionRange(introduced="2.3.0", fixed="2.31.0")],
    fixed_versions=["2.31.0"],
)
LATER = Advisory(
    id="GHSA-later",
    package="requests",
    ranges=[VersionRange(introduced="2.31.0", fixed="2.32.0")],
    fixed_versions=["2.32.0"],
)
VERSIONS = ["2.27.1", "2.30.0", "2.31.0", "2.32.0", "2.33.0", "3.0.0rc1"]


def pypi_serving(releases: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"releases": releases})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_yanked_and_fileless_releases_are_dropped():
    releases = {
        "1.0": [{"yanked": False}],
        "1.1": [{"yanked": True}],
        "1.2": [],
        "1.3": [{"yanked": True}, {"yanked": False}],
    }
    with pypi_serving(releases) as client:
        assert sorted(available_versions("example", client)) == ["1.0", "1.3"]


def test_prereleases_are_left_out_unless_asked_for():
    assert [str(v) for v in sorted_versions(VERSIONS, allow_prereleases=False)][-1] == "2.33.0"
    assert [str(v) for v in sorted_versions(VERSIONS, allow_prereleases=True)][-1] == "3.0.0rc1"


def test_versions_are_compared_properly_not_as_text():
    assert [str(v) for v in sorted_versions(["2.9.0", "2.10.0"], False)] == ["2.9.0", "2.10.0"]


def test_the_lowest_clear_version_is_chosen():
    assert lowest_safe_version(VERSIONS, [REQUESTS], "2.27.1") == "2.31.0"


def test_a_second_advisory_pushes_the_answer_higher():
    assert lowest_safe_version(VERSIONS, [REQUESTS, LATER], "2.27.1") == "2.32.0"


def test_the_answer_is_always_above_the_installed_version():
    assert lowest_safe_version(VERSIONS, [], "2.31.0") == "2.32.0"


def test_with_no_advisories_and_no_current_version_the_oldest_release_is_clear():
    assert lowest_safe_version(VERSIONS, []) == "2.27.1"


def test_there_is_no_answer_when_every_release_is_affected():
    everything = Advisory(id="GHSA-all", package="p", ranges=[VersionRange(introduced="0")])
    assert lowest_safe_version(VERSIONS, [everything]) is None


def test_a_version_that_pypi_does_not_serve_is_never_suggested():
    # 2.31.0 fixes the advisory but PyPI does not list it, so the answer must move on.
    without_the_fix = ["2.27.1", "2.30.0", "2.32.0"]
    assert lowest_safe_version(without_the_fix, [REQUESTS], "2.27.1") == "2.32.0"


def test_the_tool_reports_the_fix_and_what_it_considered(monkeypatch):
    monkeypatch.setattr(module, "advisories_by_package", lambda: {"requests": [REQUESTS]})
    monkeypatch.setattr(module, "available_versions", lambda package, client: VERSIONS)
    result = find_safe_version(SafeVersionRequest(package="requests", current_version="2.27.1"))
    assert result.safe_version == "2.31.0"
    assert result.advisories_considered == ["GHSA-j8r2"]
    assert result.versions_available == len(VERSIONS)
    assert "lowest published release" in result.reason


def test_only_the_named_advisories_are_considered(monkeypatch):
    monkeypatch.setattr(module, "advisories_by_package", lambda: {"requests": [REQUESTS, LATER]})
    monkeypatch.setattr(module, "available_versions", lambda package, client: VERSIONS)
    result = find_safe_version(
        SafeVersionRequest(
            package="requests", current_version="2.27.1", advisory_ids=["CVE-2023-32681"]
        )
    )
    assert result.advisories_considered == ["GHSA-j8r2"]
    assert result.safe_version == "2.31.0"


def test_a_package_with_no_advisories_says_so(monkeypatch):
    monkeypatch.setattr(module, "advisories_by_package", lambda: {})
    monkeypatch.setattr(module, "available_versions", lambda package, client: VERSIONS)
    result = find_safe_version(SafeVersionRequest(package="quiet-package"))
    assert result.safe_version == "2.27.1"
    assert "no advisories are on record" in result.reason


def test_an_unreachable_pypi_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(module, "advisories_by_package", lambda: {"requests": [REQUESTS]})

    def fail(package, client):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(module, "available_versions", fail)
    result = find_safe_version(SafeVersionRequest(package="requests"))
    assert result.safe_version is None
    assert "PyPI could not be read" in result.reason


def test_a_package_with_no_usable_release_is_reported(monkeypatch):
    monkeypatch.setattr(module, "advisories_by_package", lambda: {"requests": [REQUESTS]})
    monkeypatch.setattr(module, "available_versions", lambda package, client: [])
    result = find_safe_version(SafeVersionRequest(package="requests"))
    assert result.safe_version is None
    assert "no usable release" in result.reason


def test_an_advisory_nothing_fixes_leaves_the_list_open(monkeypatch):
    everything = Advisory(id="GHSA-all", package="requests", ranges=[VersionRange(introduced="0")])
    monkeypatch.setattr(module, "advisories_by_package", lambda: {"requests": [everything]})
    monkeypatch.setattr(module, "available_versions", lambda package, client: VERSIONS)
    result = find_safe_version(SafeVersionRequest(package="requests"))
    assert result.safe_version is None
    assert result.advisories_still_open == ["GHSA-all"]
