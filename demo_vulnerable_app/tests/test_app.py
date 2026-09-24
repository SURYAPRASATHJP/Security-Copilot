import hashlib

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_greet_uses_the_name_from_the_query_string(client):
    assert b"Hello Swork" in client.get("/greet?name=Swork").data


def test_greet_falls_back_to_a_default_name(client):
    assert b"Hello stranger" in client.get("/greet").data


def test_fingerprint_matches_the_standard_library_digest(client):
    body = b"upload me"
    response = client.post("/fingerprint", data=body)
    assert response.get_json() == {"sha256": hashlib.sha256(body).hexdigest()}


def test_fingerprint_handles_an_empty_body(client):
    assert (
        client.post("/fingerprint", data=b"").get_json()["sha256"]
        == hashlib.sha256(b"").hexdigest()
    )


def test_upstream_reports_the_status_code(client, monkeypatch):
    class Response:
        status_code = 204
        content = b""

    monkeypatch.setattr("app.requests.get", lambda url, timeout: Response())
    assert client.get("/upstream?url=https://example.com").get_json() == {
        "status_code": 204,
        "length": 0,
    }
