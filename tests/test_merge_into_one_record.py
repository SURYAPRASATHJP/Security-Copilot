import json

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import enrich, load_nvd_cache, read_advisories

NVD = {
    "CVE-2021-44228": {
        "cvss_score": 10.0,
        "cvss_severity": "CRITICAL",
        "cvss_vector": "CVSS:3.1/AV:N",
        "cwe_ids": ["CWE-502"],
    },
    "CVE-2020-28493": {
        "cvss_score": 5.3,
        "cvss_severity": "MEDIUM",
        "cvss_vector": "CVSS:3.1/AV:L",
        "cwe_ids": ["CWE-400", "CWE-502"],
    },
}
EPSS = {"CVE-2021-44228": 0.97, "CVE-2020-28493": 0.004}
KEV = {"CVE-2021-44228"}


def test_takes_the_highest_cvss_and_epss_across_aliases():
    advisory = Advisory(
        id="GHSA-a",
        package="jinja2",
        aliases=["CVE-2020-28493", "CVE-2021-44228"],
    )
    merged = enrich(advisory, NVD, EPSS, KEV)
    assert merged.cvss_score == 10.0
    assert merged.epss_probability == 0.97


def test_flags_an_advisory_whose_cve_is_known_exploited():
    advisory = Advisory(id="GHSA-a", package="log4j-shim", aliases=["CVE-2021-44228"])
    assert enrich(advisory, NVD, EPSS, KEV).known_exploited is True


def test_an_advisory_with_no_kev_cve_is_not_flagged():
    advisory = Advisory(id="GHSA-b", package="jinja2", aliases=["CVE-2020-28493"])
    assert enrich(advisory, NVD, EPSS, KEV).known_exploited is False


def test_cwe_ids_are_unioned_without_duplicates():
    advisory = Advisory(id="GHSA-a", package="jinja2", aliases=["CVE-2020-28493", "CVE-2021-44228"])
    assert enrich(advisory, NVD, EPSS, KEV).cwe_ids == ["CWE-400", "CWE-502"]


def test_an_advisory_with_no_cve_alias_keeps_empty_enrichment():
    advisory = Advisory(id="GHSA-only", package="requests")
    merged = enrich(advisory, NVD, EPSS, KEV)
    assert merged.cvss_score is None
    assert merged.epss_probability is None
    assert merged.known_exploited is False


def test_the_osv_vector_survives_when_nvd_has_none():
    advisory = Advisory(id="GHSA-a", package="requests", cvss_vector="CVSS:3.1/FROM-OSV")
    assert enrich(advisory, {}, {}, set()).cvss_vector == "CVSS:3.1/FROM-OSV"


def test_the_nvd_cache_skips_unreadable_files(tmp_path):
    (tmp_path / "CVE-1.json").write_text(json.dumps({"vulnerabilities": []}))
    (tmp_path / "CVE-2.json").write_text("{broken")
    (tmp_path / "notes.txt").write_text("ignored")
    assert list(load_nvd_cache(tmp_path)) == ["CVE-1"]


def test_reading_advisories_skips_blank_lines(tmp_path):
    path = tmp_path / "advisories.jsonl"
    advisory = Advisory(id="GHSA-a", package="requests")
    path.write_text(advisory.model_dump_json() + "\n\n")
    assert len(read_advisories(path)) == 1
