import pandas as pd

from app.streamlit_app import FINDING_COLUMNS, findings_table, osv_link

FINDINGS = [
    {
        "package": "werkzeug",
        "installed_version": "2.2.2",
        "advisory_id": "GHSA-2g68-c3qc-8985",
        "fixed_version": "3.0.3",
        "cvss_score": 7.5,
        "epss_probability": 0.034,
        "known_exploited": False,
    },
    {
        "package": "requests",
        "installed_version": None,
        "advisory_id": "GHSA-j8r2",
        "fixed_version": None,
        "cvss_score": None,
        "epss_probability": None,
        "known_exploited": True,
    },
]


def test_an_advisory_id_becomes_an_osv_link():
    assert osv_link("GHSA-j8r2") == "https://osv.dev/vulnerability/GHSA-j8r2"


def test_the_table_has_a_column_per_field_the_developer_needs():
    table = findings_table(FINDINGS)
    assert list(table.columns) == [*FINDING_COLUMNS.values(), "Link"]


def test_the_table_keeps_the_order_the_api_returned():
    table = findings_table(FINDINGS)
    assert list(table["Package"]) == ["werkzeug", "requests"]


def test_missing_values_stay_empty_rather_than_becoming_text():
    table = findings_table(FINDINGS)
    assert pd.isna(table["Fixed in"][1])
    assert pd.isna(table["Version"][1])
    assert "None" not in table.to_string()


def test_every_row_links_to_its_advisory():
    table = findings_table(FINDINGS)
    assert list(table["Link"]) == [
        "https://osv.dev/vulnerability/GHSA-2g68-c3qc-8985",
        "https://osv.dev/vulnerability/GHSA-j8r2",
    ]


def test_an_empty_finding_list_gives_an_empty_table():
    assert findings_table([]).empty
