import json

from copilot.data_collection.load_osv_advisories import load_osv_folder

GOOD = {
    "id": "GHSA-good",
    "affected": [{"package": {"ecosystem": "PyPI", "name": "requests"}, "ranges": []}],
}


def test_loads_every_valid_file(tmp_path):
    (tmp_path / "GHSA-good.json").write_text(json.dumps(GOOD))
    (tmp_path / "GHSA-good2.json").write_text(json.dumps({**GOOD, "id": "GHSA-good2"}))
    report = load_osv_folder(tmp_path)
    assert report.files_read == 2
    assert len(report.advisories) == 2
    assert report.failures == []
    assert report.failure_rate == 0.0


def test_a_broken_file_is_recorded_not_raised(tmp_path):
    (tmp_path / "GHSA-good.json").write_text(json.dumps(GOOD))
    (tmp_path / "GHSA-broken.json").write_text("{not json")
    report = load_osv_folder(tmp_path)
    assert len(report.advisories) == 1
    assert report.failures[0]["file"] == "GHSA-broken.json"
    assert report.failure_rate == 0.5


def test_packages_are_deduplicated(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(GOOD))
    (tmp_path / "b.json").write_text(json.dumps({**GOOD, "id": "GHSA-other"}))
    assert load_osv_folder(tmp_path).packages == {"requests"}
