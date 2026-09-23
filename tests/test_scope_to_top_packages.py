from copilot.data_collection.advisory import Advisory
from copilot.data_collection.scope_to_top_packages import (
    scope_to_packages,
    top_package_names,
    write_advisories,
)

PAYLOAD = {
    "rows": [
        {"download_count": 10, "project": "requests"},
        {"download_count": 30, "project": "boto3"},
        {"download_count": 20, "project": "urllib3"},
    ]
}


def test_most_downloaded_comes_first():
    assert top_package_names(PAYLOAD, 3) == ["boto3", "urllib3", "requests"]


def test_limit_trims_the_tail():
    assert top_package_names(PAYLOAD, 1) == ["boto3"]


def test_package_names_are_compared_normalised():
    advisories = [
        Advisory(id="GHSA-a", package="Jinja2"),
        Advisory(id="GHSA-b", package="typing_extensions"),
        Advisory(id="GHSA-c", package="some-unpopular-package"),
    ]
    scoped = scope_to_packages(advisories, ["jinja2", "typing-extensions"])
    assert [a.id for a in scoped] == ["GHSA-a", "GHSA-b"]


def test_writing_advisories_round_trips(tmp_path):
    path = tmp_path / "scoped.jsonl"
    written = write_advisories([Advisory(id="GHSA-a", package="requests")], path)
    assert written == 1
    assert Advisory.model_validate_json(path.read_text().strip()).package == "requests"
