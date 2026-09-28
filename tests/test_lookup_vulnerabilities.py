import httpx

from copilot.agents.tools import lookup_vulnerabilities as module
from copilot.agents.tools.lookup_vulnerabilities import LookupRequest, lookup_vulnerabilities
from copilot.data_collection.advisory import Advisory
from copilot.dependencies.check_my_dependencies import index_local_advisories
from copilot.dependencies.read_requirements_file import read_requirements_text
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk

GHSA = Advisory(
    id="GHSA-j8r2-6x86-q33q",
    package="requests",
    aliases=["CVE-2023-32681"],
    summary="Proxy-Authorization header leak",
    fixed_versions=["2.31.0"],
    cvss_score=6.1,
)
PASSAGE = SearchResult(
    chunk=Chunk(
        chunk_id="GHSA-j8r2|requests|structured|0",
        text="Advisory GHSA-j8r2 for package requests: fixed in 2.31.0",
        strategy="structured",
        advisory_id="GHSA-j8r2-6x86-q33q",
        package="requests",
        chunk_index=0,
    ),
    score=0.9,
    source="reranked",
)


def osv_responds_with(monkeypatch, payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    original = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original(*args, transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx, "Client", fake_client)
    monkeypatch.setattr(module, "local_advisory_index", lambda: index_local_advisories([GHSA]))


def test_packages_are_checked_against_osv(monkeypatch):
    osv_responds_with(monkeypatch, {"results": [{"vulns": [{"id": "GHSA-j8r2-6x86-q33q"}]}]})
    packages = read_requirements_text("requests==2.27.1\n").requirements
    result = lookup_vulnerabilities(LookupRequest(packages=packages))
    assert result.packages_checked == 1
    assert result.affected_packages == ["requests"]
    assert result.findings[0].fixed_version == "2.31.0"


def test_a_clean_package_list_produces_no_findings(monkeypatch):
    osv_responds_with(monkeypatch, {"results": [{}]})
    packages = read_requirements_text("requests==2.31.0\n").requirements
    result = lookup_vulnerabilities(LookupRequest(packages=packages))
    assert result.findings == []
    assert result.affected_packages == []
    assert result.packages_checked == 1


def test_parser_warnings_reach_the_caller(monkeypatch):
    osv_responds_with(monkeypatch, {"results": [{}]})
    packages = read_requirements_text("urllib3>=1.26\n").requirements
    result = lookup_vulnerabilities(LookupRequest(packages=packages))
    assert result.packages_checked == 1


def test_no_packages_and_no_question_does_nothing(monkeypatch):
    result = lookup_vulnerabilities(LookupRequest())
    assert result.findings == []
    assert result.passages == []
    assert result.packages_checked == 0


def test_a_question_searches_the_corpus(monkeypatch):
    monkeypatch.setattr(module, "hybrid_search", lambda q, s, k: [PASSAGE])
    monkeypatch.setattr(module, "rerank_results", lambda q, results, k: list(results)[:k])
    result = lookup_vulnerabilities(LookupRequest(question="proxy header leak", passages=5))
    assert [p.advisory_id for p in result.passages] == ["GHSA-j8r2-6x86-q33q"]
    assert result.packages_checked == 0


def test_the_requested_passage_count_is_honoured(monkeypatch):
    monkeypatch.setattr(module, "hybrid_search", lambda q, s, k: [PASSAGE] * 10)
    monkeypatch.setattr(module, "rerank_results", lambda q, results, k: list(results)[:k])
    result = lookup_vulnerabilities(LookupRequest(question="anything", passages=3))
    assert len(result.passages) == 3
