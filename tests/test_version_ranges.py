from copilot.data_collection.advisory import Advisory, VersionRange
from copilot.dependencies.version_ranges import (
    a_safe_version,
    an_affected_version,
    is_version_affected,
    parse_version,
)

REQUESTS = Advisory(
    id="GHSA-j8r2-6x86-q33q",
    package="requests",
    ranges=[VersionRange(introduced="2.3.0", fixed="2.31.0")],
    fixed_versions=["2.31.0"],
    affected_versions=["2.3.0", "2.27.1", "2.30.0"],
)
TWO_WINDOWS = Advisory(
    id="GHSA-two",
    package="jinja2",
    ranges=[
        VersionRange(introduced="1.0", fixed="1.5"),
        VersionRange(introduced="2.0", fixed="2.5"),
    ],
    fixed_versions=["1.5", "2.5"],
)
OPEN_ENDED = Advisory(id="GHSA-open", package="abandoned", ranges=[VersionRange(introduced="0")])
LAST_AFFECTED = Advisory(
    id="GHSA-last", package="pyyaml", ranges=[VersionRange(introduced="0", last_affected="5.3")]
)


def test_a_version_inside_the_window_is_affected():
    assert is_version_affected(REQUESTS, "2.27.1") is True
    assert is_version_affected(REQUESTS, "2.30.0") is True


def test_the_fixed_version_itself_is_not_affected():
    assert is_version_affected(REQUESTS, "2.31.0") is False


def test_a_version_after_the_fix_is_not_affected():
    assert is_version_affected(REQUESTS, "2.32.0") is False


def test_a_version_before_the_window_is_not_affected():
    assert is_version_affected(REQUESTS, "2.2.1") is False


def test_the_introduced_boundary_is_affected():
    assert is_version_affected(REQUESTS, "2.3.0") is True


def test_a_version_between_two_windows_is_not_affected():
    assert is_version_affected(TWO_WINDOWS, "1.7") is False
    assert is_version_affected(TWO_WINDOWS, "1.2") is True
    assert is_version_affected(TWO_WINDOWS, "2.1") is True
    assert is_version_affected(TWO_WINDOWS, "2.5") is False


def test_an_open_window_affects_everything_from_its_start():
    assert is_version_affected(OPEN_ENDED, "0.1") is True
    assert is_version_affected(OPEN_ENDED, "99.0") is True


def test_last_affected_is_inclusive():
    assert is_version_affected(LAST_AFFECTED, "5.3") is True
    assert is_version_affected(LAST_AFFECTED, "5.3.1") is False


def test_a_version_listed_explicitly_is_affected_even_without_a_range():
    listed = Advisory(id="GHSA-listed", package="p", affected_versions=["1.0b1"])
    assert is_version_affected(listed, "1.0b1") is True


def test_an_advisory_with_no_bounds_affects_nothing():
    assert is_version_affected(Advisory(id="GHSA-none", package="p"), "1.0") is False


def test_an_unreadable_version_is_not_claimed_as_affected():
    assert is_version_affected(REQUESTS, "not-a-version") is False
    assert parse_version("not-a-version") is None


def test_a_prerelease_inside_the_window_is_affected():
    assert is_version_affected(REQUESTS, "2.30.0rc1") is True


def test_an_affected_example_version_is_really_affected():
    for advisory in (REQUESTS, TWO_WINDOWS, LAST_AFFECTED, OPEN_ENDED):
        example = an_affected_version(advisory)
        assert example is not None
        assert is_version_affected(advisory, example) is True


def test_a_safe_example_version_is_really_safe():
    for advisory in (REQUESTS, TWO_WINDOWS):
        example = a_safe_version(advisory)
        assert example is not None
        assert is_version_affected(advisory, example) is False


def test_there_is_no_safe_example_when_nothing_is_fixed():
    assert a_safe_version(OPEN_ENDED) is None


def test_the_earliest_fix_is_the_one_offered_as_safe():
    assert a_safe_version(TWO_WINDOWS) == "1.5"
