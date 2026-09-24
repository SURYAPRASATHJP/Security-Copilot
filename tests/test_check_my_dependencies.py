import httpx

from copilot.data_collection.advisory import Advisory
from copilot.dependencies.check_my_dependencies import (
    Finding,
    advisory_ids_from_batch,
    build_findings,
    build_queries,
    check_requirements,
    deduplicate_findings,
    index_local_advisories,
    lowest_fixed_version,
    risk_key,
)
from copilot.dependencies.read_requirements_file import read_requirements_text

GHSA = Advisory(
    id="GHSA-j8r2-6x86-q33q",
    package="requests",
    aliases=["CVE-2023-32681"],
    summary="Proxy-Authorization header leak",
    fixed_versions=["2.31.0"],
    severity="MODERATE",
    cvss_score=6.1,
    epss_probability=0.03,
)
PYSEC = Advisory(
    id="PYSEC-2023-74",
    package="requests",
    aliases=["CVE-2023-32681", "GHSA-j8r2-6x86-q33q"],
    fixed_versions=["2.31.0"],
)


def fake_client(payload: dict) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )


def test_lowest_fixed_version_picks_the_earliest():
    advisory = Advisory(id="a", package="p", fixed_versions=["2.31.0", "1.26.5", "3.0.0"])
    assert lowest_fixed_version(advisory) == "1.26.5"


def test_lowest_fixed_version_ignores_versions_it_cannot_parse():
    advisory = Advisory(id="a", package="p", fixed_versions=["not-a-version", "2.0.0"])
    assert lowest_fixed_version(advisory) == "2.0.0"


def test_lowest_fixed_version_is_none_when_nothing_is_fixed():
    assert lowest_fixed_version(Advisory(id="a", package="p")) is None


def test_advisories_are_indexed_by_every_id_they_answer_to():
    index = index_local_advisories([GHSA])
    assert index[("requests", "GHSA-j8r2-6x86-q33q")] is GHSA
    assert index[("requests", "CVE-2023-32681")] is GHSA


def test_a_pinned_requirement_is_queried_with_its_version():
    parsed = read_requirements_text("requests==2.27.1\nurllib3>=1.26\n")
    queries = build_queries(parsed.requirements)
    assert queries[0] == {"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.27.1"}
    assert "version" not in queries[1]


def test_advisory_ids_survive_an_empty_result_slot():
    payload = {"results": [{"vulns": [{"id": "GHSA-a"}]}, {}, {"vulns": []}]}
    assert advisory_ids_from_batch(payload) == [["GHSA-a"], [], []]


def test_a_finding_without_a_local_record_still_reports_the_advisory_id():
    parsed = read_requirements_text("requests==2.27.1\n")
    findings = build_findings(parsed.requirements, [["GHSA-unknown"]], {})
    assert findings[0].advisory_id == "GHSA-unknown"
    assert findings[0].fixed_version is None
    assert findings[0].summary == ""


def test_a_finding_carries_the_local_metadata():
    parsed = read_requirements_text("requests==2.27.1\n")
    findings = build_findings(
        parsed.requirements, [["GHSA-j8r2-6x86-q33q"]], index_local_advisories([GHSA])
    )
    assert findings[0].fixed_version == "2.31.0"
    assert findings[0].cvss_score == 6.1
    assert findings[0].summary == "Proxy-Authorization header leak"


def test_the_ghsa_record_wins_and_the_mirror_id_is_kept_as_an_alias():
    parsed = read_requirements_text("requests==2.27.1\n")
    index = index_local_advisories([GHSA, PYSEC])
    findings = build_findings(
        parsed.requirements, [["PYSEC-2023-74", "GHSA-j8r2-6x86-q33q"]], index
    )
    assert len(findings) == 1
    assert findings[0].advisory_id == "GHSA-j8r2-6x86-q33q"
    assert "PYSEC-2023-74" in findings[0].aliases


def test_advisories_without_a_shared_cve_are_not_collapsed():
    one = Finding(package="p", canonical_name="p", installed_version="1", advisory_id="GHSA-a")
    two = Finding(package="p", canonical_name="p", installed_version="1", advisory_id="GHSA-b")
    assert len(deduplicate_findings([one, two])) == 2


def test_known_exploited_sorts_above_a_higher_scoring_finding():
    exploited = Finding(
        package="p",
        canonical_name="p",
        installed_version="1",
        advisory_id="GHSA-kev",
        known_exploited=True,
        cvss_score=4.0,
    )
    severe = Finding(
        package="p",
        canonical_name="p",
        installed_version="1",
        advisory_id="GHSA-high",
        cvss_score=9.8,
        epss_probability=0.9,
    )
    assert [f.advisory_id for f in sorted([severe, exploited], key=risk_key)] == [
        "GHSA-kev",
        "GHSA-high",
    ]


def test_epss_breaks_the_tie_before_cvss():
    likely = Finding(
        package="p",
        canonical_name="p",
        installed_version="1",
        advisory_id="GHSA-likely",
        epss_probability=0.5,
        cvss_score=5.0,
    )
    severe = Finding(
        package="p",
        canonical_name="p",
        installed_version="1",
        advisory_id="GHSA-severe",
        epss_probability=0.1,
        cvss_score=9.9,
    )
    assert [f.advisory_id for f in sorted([severe, likely], key=risk_key)] == [
        "GHSA-likely",
        "GHSA-severe",
    ]


def test_check_requirements_reports_what_it_checked_and_the_parser_warnings():
    parsed = read_requirements_text("requests==2.27.1\nurllib3>=1.26\n")
    payload = {"results": [{"vulns": [{"id": "GHSA-j8r2-6x86-q33q"}]}, {}]}
    with fake_client(payload) as client:
        report = check_requirements(parsed, index_local_advisories([GHSA]), client)
    assert report.packages_checked == 2
    assert report.affected_packages == ["requests"]
    assert any("urllib3 is not pinned" in w for w in report.warnings)


def test_a_file_with_no_requirements_makes_no_request():
    parsed = read_requirements_text("# nothing here\n")
    with fake_client({"results": []}) as client:
        report = check_requirements(parsed, {}, client)
    assert report.findings == []
    assert report.packages_checked == 0


def test_the_advisory_url_points_at_osv():
    finding = Finding(
        package="requests",
        canonical_name="requests",
        installed_version="2.27.1",
        advisory_id="GHSA-a",
    )
    assert finding.advisory_url == "https://osv.dev/vulnerability/GHSA-a"
