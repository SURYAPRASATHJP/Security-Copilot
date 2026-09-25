from copilot.data_collection.advisory import advisories_from_osv

OSV_RECORD = {
    "id": "GHSA-j8r2-6x86-q33q",
    "summary": "Unintended leak of Proxy-Authorization header in requests",
    "details": "Requests is leaking Proxy-Authorization headers to destination servers.",
    "aliases": ["CVE-2023-32681"],
    "published": "2023-05-26T18:30:22Z",
    "modified": "2023-06-01T10:00:00Z",
    "database_specific": {"severity": "MODERATE"},
    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N"}],
    "references": [
        {"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-j8r2-6x86-q33q"},
        {"type": "WEB", "url": "https://github.com/psf/requests/pull/6401"},
    ],
    "affected": [
        {
            "package": {"ecosystem": "PyPI", "name": "requests"},
            "ranges": [
                {"type": "ECOSYSTEM", "events": [{"introduced": "2.3.0"}, {"fixed": "2.31.0"}]}
            ],
            "versions": ["2.3.0", "2.30.0"],
        },
        {"package": {"ecosystem": "Go", "name": "requests"}, "ranges": []},
    ],
}


def test_builds_one_advisory_per_pypi_package():
    advisories = advisories_from_osv(OSV_RECORD)
    assert len(advisories) == 1
    assert advisories[0].package == "requests"


def test_captures_the_fixed_version_and_range():
    advisory = advisories_from_osv(OSV_RECORD)[0]
    assert advisory.fixed_versions == ["2.31.0"]
    assert advisory.ranges[0].introduced == "2.3.0"
    assert advisory.ranges[0].fixed == "2.31.0"


def test_splits_aliases_into_cve_and_ghsa_ids():
    advisory = advisories_from_osv(OSV_RECORD)[0]
    assert advisory.cve_ids == ["CVE-2023-32681"]
    assert advisory.ghsa_ids == ["GHSA-j8r2-6x86-q33q"]
    assert advisory.all_ids == ["GHSA-j8r2-6x86-q33q", "CVE-2023-32681"]


def test_keeps_severity_word_and_cvss_vector():
    advisory = advisories_from_osv(OSV_RECORD)[0]
    assert advisory.severity == "MODERATE"
    assert advisory.cvss_vector.startswith("CVSS:3.1/")


def test_keeps_every_reference_url():
    advisory = advisories_from_osv(OSV_RECORD)[0]
    assert len(advisory.references) == 2


def test_a_record_with_no_pypi_package_yields_nothing():
    record = {"id": "GHSA-x", "affected": [{"package": {"ecosystem": "npm", "name": "lodash"}}]}
    assert advisories_from_osv(record) == []


def test_two_introduced_events_become_two_ranges():
    record = {
        "id": "GHSA-y",
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "jinja2"},
                "ranges": [
                    {
                        "events": [
                            {"introduced": "1.0"},
                            {"fixed": "1.5"},
                            {"introduced": "2.0"},
                            {"fixed": "2.5"},
                        ]
                    }
                ],
            }
        ],
    }
    advisory = advisories_from_osv(record)[0]
    assert [(r.introduced, r.fixed) for r in advisory.ranges] == [("1.0", "1.5"), ("2.0", "2.5")]


def test_a_last_affected_event_is_kept():
    record = {
        "id": "GHSA-z",
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "pyyaml"},
                "ranges": [{"events": [{"introduced": "0"}, {"last_affected": "5.3"}]}],
            }
        ],
    }
    advisory = advisories_from_osv(record)[0]
    assert advisory.ranges[0].last_affected == "5.3"
    assert advisory.fixed_versions == []


def test_two_affected_blocks_for_one_package_become_one_advisory():
    record = {
        "id": "GHSA-dup",
        "affected": [
            {
                "package": {"ecosystem": "PyPI", "name": "protobuf"},
                "ranges": [{"events": [{"introduced": "3.0"}, {"fixed": "3.18.3"}]}],
                "versions": ["3.0"],
            },
            {
                "package": {"ecosystem": "PyPI", "name": "Protobuf"},
                "ranges": [{"events": [{"introduced": "4.0"}, {"fixed": "4.21.6"}]}],
                "versions": ["4.0"],
            },
        ],
    }
    advisories = advisories_from_osv(record)
    assert len(advisories) == 1
    assert advisories[0].fixed_versions == ["3.18.3", "4.21.6"]
    assert advisories[0].affected_versions == ["3.0", "4.0"]
    assert len(advisories[0].ranges) == 2


def test_an_identical_range_repeated_is_not_duplicated():
    block = {
        "package": {"ecosystem": "PyPI", "name": "redis"},
        "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.5.3"}]}],
    }
    advisories = advisories_from_osv({"id": "GHSA-same", "affected": [block, dict(block)]})
    assert len(advisories) == 1
    assert len(advisories[0].ranges) == 1
    assert advisories[0].fixed_versions == ["4.5.3"]
