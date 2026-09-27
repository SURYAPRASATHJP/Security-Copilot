import httpx
import pandas as pd

from app.streamlit_app import FINDING_COLUMNS, error_detail, findings_table, osv_link

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


def test_a_missing_score_does_not_render_as_the_word_none():
    table = findings_table(FINDINGS)
    assert "None" not in table.to_string()
    assert str(table["CVSS"].dtype).startswith("float")
    assert str(table["EPSS"].dtype).startswith("float")


def failed_request(status, body, content_type="application/json"):
    request = httpx.Request("POST", "http://127.0.0.1:8000/ask")
    response = httpx.Response(
        status, content=body, headers={"content-type": content_type}, request=request
    )
    return httpx.HTTPStatusError("failed", request=request, response=response)


def test_a_json_error_body_shows_its_detail():
    error = failed_request(503, b'{"detail": "GROQ_API_KEY is not set."}')
    assert error_detail(error) == "GROQ_API_KEY is not set."


def test_an_html_error_body_does_not_crash_the_page():
    error = failed_request(500, b"<html>Internal Server Error</html>", "text/html")
    detail = error_detail(error)
    assert "500" in detail
    assert "Internal Server Error" in detail


def test_an_empty_error_body_still_names_the_status():
    error = failed_request(502, b"")
    assert "502" in error_detail(error)


def test_json_without_a_detail_field_falls_back_to_the_body():
    error = failed_request(422, b'{"errors": ["bad input"]}')
    assert "422" in error_detail(error)


def test_a_connection_failure_with_no_response_is_readable():
    assert "could not be reached" in error_detail(httpx.ConnectError("refused"))
