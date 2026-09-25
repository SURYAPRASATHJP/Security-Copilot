from copilot.data_collection.advisory import Advisory
from copilot.rag.refresh_index_daily import (
    ids_changed_since,
    parse_feed,
    read_watermark,
    replace_advisories,
    write_watermark,
)

FEED = """\
2026-10-07T21:00:05.389737802Z,GHSA-newest
2026-10-07T20:00:00.000000000Z,GHSA-middle
2026-10-06T09:00:00.000000000Z,GHSA-oldest
"""


def test_the_feed_is_read_as_timestamp_and_id_pairs():
    rows = parse_feed(FEED)
    assert len(rows) == 3
    assert rows[0] == ("2026-10-07T21:00:05.389737802Z", "GHSA-newest")


def test_a_malformed_feed_line_is_skipped():
    assert parse_feed("no comma here\n2026-01-01T00:00:00Z,GHSA-a\n") == [
        ("2026-01-01T00:00:00Z", "GHSA-a")
    ]


def test_only_rows_newer_than_the_watermark_are_returned():
    changed = ids_changed_since(parse_feed(FEED), "2026-10-07T20:00:00.000000000Z")
    assert changed == ["GHSA-newest"]


def test_walking_stops_at_the_watermark_rather_than_scanning_on():
    changed = ids_changed_since(parse_feed(FEED), "2026-10-06T09:00:00.000000000Z")
    assert changed == ["GHSA-newest", "GHSA-middle"]


def test_a_watermark_newer_than_everything_finds_no_changes():
    assert ids_changed_since(parse_feed(FEED), "2026-12-01T00:00:00Z") == []


def test_no_watermark_means_the_whole_feed_is_new():
    assert len(ids_changed_since(parse_feed(FEED), None)) == 3


def test_a_watermark_round_trips_through_disk(tmp_path):
    path = tmp_path / "last_refresh.txt"
    assert read_watermark(path) is None
    write_watermark(path, "2026-10-07T21:00:05Z")
    assert read_watermark(path) == "2026-10-07T21:00:05Z"


def test_a_rebuilt_advisory_replaces_the_old_one():
    old = Advisory(id="GHSA-a", package="requests", summary="old text")
    other = Advisory(id="GHSA-b", package="flask", summary="untouched")
    new = Advisory(id="GHSA-a", package="requests", summary="new text")
    merged = replace_advisories([old, other], [new])
    assert len(merged) == 2
    assert next(a for a in merged if a.id == "GHSA-a").summary == "new text"
    assert next(a for a in merged if a.id == "GHSA-b").summary == "untouched"


def test_the_same_advisory_for_a_different_package_is_kept_separately():
    one = Advisory(id="GHSA-a", package="requests")
    two = Advisory(id="GHSA-a", package="flask")
    assert len(replace_advisories([one], [two])) == 2


def test_a_brand_new_advisory_is_added():
    merged = replace_advisories([], [Advisory(id="GHSA-new", package="requests")])
    assert [a.id for a in merged] == ["GHSA-new"]
