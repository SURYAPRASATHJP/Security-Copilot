import json

import pytest
from fastapi.testclient import TestClient

from api import main
from copilot import llm_client
from copilot.dependencies.check_my_dependencies import DependencyReport, Finding
from copilot.rag import answer_with_citations
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk

FINDING = Finding(
    package="requests",
    canonical_name="requests",
    installed_version="2.27.1",
    advisory_id="GHSA-j8r2",
    aliases=["CVE-2023-32681"],
    summary="Proxy-Authorization header leak",
    fixed_version="2.31.0",
    cvss_score=6.1,
)
PASSAGE = SearchResult(
    chunk=Chunk(
        chunk_id="GHSA-j8r2|requests|structured|0",
        text="Advisory GHSA-j8r2 for package requests: fixed in 2.31.0",
        strategy="structured",
        advisory_id="GHSA-j8r2",
        package="requests",
        chunk_index=0,
        cve_ids=["CVE-2023-32681"],
    ),
    score=0.9,
    source="reranked",
)
REPORT = DependencyReport(
    findings=[FINDING],
    packages_checked=2,
    warnings=["line 2: urllib3 is not pinned to one version, so the check uses the newest"],
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "run_check", lambda text: REPORT)
    return TestClient(main.app)


@pytest.fixture
def canned_answer(monkeypatch):
    def fake_ask_llm(messages, json_schema=None, temperature=0, **kwargs):
        return json.dumps(
            {
                "answer": "Upgrade requests to 2.31.0.",
                "citations": ["GHSA-j8r2"],
                "affected_packages": ["requests"],
                "confidence": 0.92,
            }
        )

    monkeypatch.setattr(llm_client, "ask_llm", fake_ask_llm)
    monkeypatch.setattr(
        main,
        "answer_question",
        lambda question, findings=(), strategy="structured": answer_with_citations.answer_question(
            question, findings=findings, results=[PASSAGE]
        ),
    )


def test_health_reports_what_is_ready(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model"] == "openai/gpt-oss-120b"
    assert "corpus_built" in body
    assert "groq_key_present" in body


def test_checking_dependencies_returns_the_findings(client):
    response = client.post("/check-dependencies", json={"requirements": "requests==2.27.1\n"})
    assert response.status_code == 200
    body = response.json()
    assert body["packages_checked"] == 2
    assert body["packages_affected"] == ["requests"]
    assert body["findings"][0]["advisory_id"] == "GHSA-j8r2"
    assert body["findings"][0]["fixed_version"] == "2.31.0"


def test_an_unpinned_package_warning_reaches_the_caller(client):
    body = client.post("/check-dependencies", json={"requirements": "urllib3\n"}).json()
    assert any("not pinned" in warning for warning in body["warnings"])


def test_a_missing_requirements_field_is_rejected(client):
    assert client.post("/check-dependencies", json={}).status_code == 422


def test_an_uploaded_file_is_checked(client):
    response = client.post(
        "/check-dependencies/upload",
        files={"file": ("requirements.txt", b"requests==2.27.1\n", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["packages_affected"] == ["requests"]


def test_asking_a_general_question_skips_the_dependency_check(client, canned_answer):
    body = client.post("/ask", json={"question": "What is CVE-2023-32681 about?"}).json()
    assert body["checked_dependencies"] is False
    assert body["answer"] == "Upgrade requests to 2.31.0."
    assert body["citations"] == ["GHSA-j8r2"]


def test_asking_about_my_packages_runs_the_check_first(client, canned_answer):
    body = client.post(
        "/ask",
        json={"question": "Am I affected?", "requirements": "requests==2.27.1\n"},
    ).json()
    assert body["checked_dependencies"] is True


def test_a_question_about_my_packages_without_a_file_still_answers(client, canned_answer):
    body = client.post("/ask", json={"question": "Am I affected?"}).json()
    assert body["checked_dependencies"] is False


def test_every_source_carries_a_link_to_osv(client, canned_answer):
    body = client.post("/ask", json={"question": "What is CVE-2023-32681 about?"}).json()
    assert body["sources"][0]["url"] == "https://osv.dev/vulnerability/GHSA-j8r2"
    assert body["sources"][0]["package"] == "requests"


def test_a_missing_key_is_reported_as_unavailable_not_a_crash(client, monkeypatch):
    from copilot.settings import MISSING_KEY_MESSAGE, MissingGroqKeyError

    def raise_missing(*args, **kwargs):
        raise MissingGroqKeyError(MISSING_KEY_MESSAGE)

    monkeypatch.setattr(main, "answer_question", raise_missing)
    response = client.post("/ask", json={"question": "What is CVE-2023-32681 about?"})
    assert response.status_code == 503
    assert ".env" in response.json()["detail"]
