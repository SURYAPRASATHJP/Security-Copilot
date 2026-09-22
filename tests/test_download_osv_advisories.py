import zipfile

import pytest

from copilot.data_collection.download_osv_advisories import (
    advisory_members,
    extract_advisories,
)


def _zip_with(tmp_path, names):
    archive_path = tmp_path / "all.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in names:
            archive.writestr(name, '{"id": "GHSA-test"}')
    return archive_path


def test_extracts_only_the_advisory_files(tmp_path):
    archive_path = _zip_with(tmp_path, ["GHSA-aaaa.json", "GHSA-bbbb.json", "README.txt"])
    count = extract_advisories(archive_path, tmp_path / "osv_pypi")
    assert count == 2
    assert sorted(p.name for p in (tmp_path / "osv_pypi").iterdir()) == [
        "GHSA-aaaa.json",
        "GHSA-bbbb.json",
    ]


def test_refuses_an_entry_that_escapes_the_target(tmp_path):
    archive_path = _zip_with(tmp_path, ["../escaped.json"])
    with zipfile.ZipFile(archive_path) as archive, pytest.raises(ValueError, match="escaped"):
        advisory_members(archive)
