import json

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.fetch_nvd_details import (
    cache_path,
    cve_ids_in_scope,
    extract_details,
)

NVD_PAYLOAD = {
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2023-32681",
                "metrics": {
                    "cvssMetricV31": [
                        {
                            "cvssData": {
                                "baseScore": 6.1,
                                "baseSeverity": "MEDIUM",
                                "vectorString": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N",
                            }
                        }
                    ]
                },
                "weaknesses": [
                    {"description": [{"lang": "en", "value": "CWE-200"}]},
                    {"description": [{"lang": "en", "value": "CWE-200"}]},
                    {"description": [{"lang": "en", "value": "NVD-CWE-noinfo"}]},
                ],
            }
        }
    ]
}


def test_pulls_score_severity_and_vector():
    details = extract_details(NVD_PAYLOAD)
    assert details["cvss_score"] == 6.1
    assert details["cvss_severity"] == "MEDIUM"
    assert details["cvss_vector"].startswith("CVSS:3.1/")


def test_cwe_ids_are_deduplicated_and_non_cwe_values_dropped():
    assert extract_details(NVD_PAYLOAD)["cwe_ids"] == ["CWE-200"]


def test_an_empty_response_gives_empty_details():
    details = extract_details({"vulnerabilities": []})
    assert details == {
        "cvss_score": None,
        "cvss_severity": None,
        "cvss_vector": None,
        "cwe_ids": [],
    }


def test_falls_back_to_an_older_metric_version():
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "metrics": {
                        "cvssMetricV2": [
                            {"cvssData": {"baseScore": 5.0, "vectorString": "AV:N/AC:L/Au:N"}}
                        ]
                    }
                }
            }
        ]
    }
    assert extract_details(payload)["cvss_score"] == 5.0


def test_cve_ids_are_collected_once_each_and_sorted(tmp_path):
    path = tmp_path / "scoped.jsonl"
    advisories = [
        Advisory(id="GHSA-a", package="requests", aliases=["CVE-2023-32681", "GHSA-a"]),
        Advisory(id="GHSA-b", package="requests", aliases=["CVE-2023-32681"]),
        Advisory(id="GHSA-c", package="jinja2", aliases=["CVE-2020-28493"]),
    ]
    path.write_text("\n".join(a.model_dump_json() for a in advisories), encoding="utf-8")
    assert cve_ids_in_scope(path) == ["CVE-2020-28493", "CVE-2023-32681"]


def test_cache_path_is_named_after_the_cve(tmp_path):
    assert cache_path("CVE-2023-32681", tmp_path).name == "CVE-2023-32681.json"


def test_a_cached_file_is_valid_json(tmp_path):
    target = cache_path("CVE-1", tmp_path)
    target.write_text(json.dumps(NVD_PAYLOAD), encoding="utf-8")
    assert extract_details(json.loads(target.read_text()))["cvss_score"] == 6.1
