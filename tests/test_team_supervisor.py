import json

from langgraph.graph import END

from copilot import llm_client
from copilot.agents import team_supervisor as module
from copilot.agents.agent_state import TriageReport
from copilot.agents.team_supervisor import (
    FIXER,
    ReviewVerdict,
    analyst,
    build_team,
    fixer,
    grade_passages,
    rank_findings,
    reviewer,
    route_after_review,
    scanner,
    search_until_useful,
)
from copilot.agents.tools.check_if_code_uses_package import (
    FUNCTION_NOT_CALLED,
    NOT_USED,
    USED,
    UsageResult,
)
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk

FINDINGS = [
    {
        "package": "werkzeug",
        "installed_version": "2.2.2",
        "advisory_id": "GHSA-werkzeug",
        "fixed_version": "3.0.3",
        "epss_probability": 0.034,
        "cvss_score": 7.5,
    },
    {
        "package": "requests",
        "installed_version": "2.27.1",
        "advisory_id": "GHSA-requests",
        "fixed_version": "2.31.0",
        "epss_probability": 0.029,
        "cvss_score": 6.1,
    },
]


def usage_of(verdicts: dict):
    def fake(request):
        return UsageResult(package=request.package, verdict=verdicts[request.package])

    return fake


def passage(advisory_id, text="some advisory text"):
    return SearchResult(
        chunk=Chunk(
            chunk_id=f"{advisory_id}|p|structured|0",
            text=text,
            strategy="structured",
            advisory_id=advisory_id,
            package="requests",
            chunk_index=0,
        ),
        score=5.0,
        source="reranked",
    )


def test_a_used_package_outranks_an_unused_one_with_a_higher_score(monkeypatch):
    monkeypatch.setattr(
        module, "check_if_code_uses_package", usage_of({"werkzeug": NOT_USED, "requests": USED})
    )
    ranked = rank_findings("demo", FINDINGS)
    assert [risk.package for risk in ranked] == ["requests", "werkzeug"]
    assert ranked[0].rank == 1


def test_exploit_probability_breaks_the_tie_within_the_same_usage(monkeypatch):
    monkeypatch.setattr(
        module, "check_if_code_uses_package", usage_of({"werkzeug": USED, "requests": USED})
    )
    ranked = rank_findings("demo", FINDINGS)
    assert [risk.package for risk in ranked] == ["werkzeug", "requests"]


def test_an_uncalled_vulnerable_function_ranks_below_a_called_one(monkeypatch):
    monkeypatch.setattr(
        module,
        "check_if_code_uses_package",
        usage_of({"werkzeug": FUNCTION_NOT_CALLED, "requests": USED}),
    )
    assert [risk.package for risk in rank_findings("demo", FINDINGS)] == ["requests", "werkzeug"]


def test_the_scanner_says_so_when_there_is_no_manifest():
    update = scanner({"repository": "fixtures/no_manifest", "steps": 0})
    assert update["packages"] == []
    assert "no manifest" in update["plan"][0]


def test_the_analyst_returns_an_empty_report_when_there_is_nothing_to_rank():
    update = analyst({"repository": "demo", "findings": [], "steps": 0})
    assert TriageReport.model_validate(update["report"]).ranked == []


def test_the_fixer_skips_a_package_the_code_never_uses(monkeypatch):
    report = TriageReport(
        repository="demo",
        ranked=[
            module.PackageRisk(
                package="certifi", advisory_id="GHSA-certifi", usage=NOT_USED, rank=1
            )
        ],
    )
    monkeypatch.setattr(module, "run_project_tests", lambda request: _passing())
    update = fixer({"repository": "demo", "report": report.model_dump(), "steps": 0})
    assert update["upgrades"] == {}


def _passing():
    from copilot.agents.tools.run_project_tests import ProjectTestResult

    return ProjectTestResult(passed=True)


def test_the_reviewer_accepts_when_the_tests_passed():
    update = reviewer(
        {"upgrades": {"flask": "3.1.3"}, "test_results": {"passed": True}, "steps": 0}
    )
    verdict = ReviewVerdict.model_validate(update["review"])
    assert verdict.accepted is True
    assert verdict.send_back is False


def test_the_reviewer_sends_a_failing_test_run_back():
    update = reviewer(
        {"upgrades": {"flask": "3.1.3"}, "test_results": {"passed": False}, "steps": 0}
    )
    verdict = ReviewVerdict.model_validate(update["review"])
    assert verdict.accepted is False
    assert verdict.send_back is True
    assert "tests did not pass" in verdict.reason


def test_the_reviewer_separates_an_install_failure_from_a_test_failure():
    update = reviewer(
        {"upgrades": {"flask": "3.1.3"}, "test_results": {"install_failed": True}, "steps": 0}
    )
    assert "did not install" in ReviewVerdict.model_validate(update["review"]).reason


def test_the_reviewer_only_sends_back_once():
    update = reviewer(
        {
            "upgrades": {"flask": "3.1.3"},
            "test_results": {"passed": False},
            "plan": ["sent back to the fixer: the project's tests did not pass"],
            "steps": 0,
        }
    )
    assert ReviewVerdict.model_validate(update["review"]).send_back is False


def test_nothing_to_upgrade_is_accepted_without_a_test_run():
    update = reviewer({"upgrades": {}, "test_results": None, "steps": 0})
    assert ReviewVerdict.model_validate(update["review"]).accepted is True


def test_routing_sends_work_back_to_the_fixer_only_when_asked():
    assert route_after_review({"review": {"send_back": True}}) == FIXER
    assert route_after_review({"review": {"send_back": False}}) == END
    assert route_after_review({}) == END


def test_the_graph_has_the_supervisor_s_four_workers():
    nodes = set(build_team().compile().get_graph().nodes)
    assert {"scanner", "analyst", "fixer", "reviewer"}.issubset(nodes)


def test_passages_that_answer_the_question_need_no_rewrite(monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "ask_llm",
        lambda *a, **k: json.dumps({"answers_the_question": True, "better_query": None}),
    )
    good, better = grade_passages("what fixes it?", [passage("GHSA-a")])
    assert good is True
    assert better is None


def test_no_passages_at_all_is_graded_as_not_answering():
    assert grade_passages("anything", []) == (False, None)


def test_a_reply_that_is_not_json_is_treated_as_good_enough(monkeypatch):
    monkeypatch.setattr(llm_client, "ask_llm", lambda *a, **k: "not json")
    assert grade_passages("anything", [passage("GHSA-a")]) == (True, None)


def test_a_vague_question_is_searched_again_with_a_better_query(monkeypatch):
    asked = []

    def fake_lookup(request):
        asked.append(request.question)
        return _result([passage("GHSA-a")])

    replies = iter(
        [
            json.dumps({"answers_the_question": False, "better_query": "proxy header leak"}),
            json.dumps({"answers_the_question": True, "better_query": None}),
        ]
    )
    monkeypatch.setattr(module, "lookup_vulnerabilities", fake_lookup)
    monkeypatch.setattr(llm_client, "ask_llm", lambda *a, **k: next(replies))

    passages, rewrites = search_until_useful("the thing with the header")
    assert rewrites == 1
    assert asked == ["the thing with the header", "proxy header leak"]
    assert len(passages) == 1


def test_the_rewrite_loop_gives_up_after_its_limit(monkeypatch):
    monkeypatch.setattr(module, "lookup_vulnerabilities", lambda r: _result([passage("GHSA-a")]))
    monkeypatch.setattr(
        llm_client,
        "ask_llm",
        lambda *a, **k: json.dumps({"answers_the_question": False, "better_query": "again"}),
    )
    _, rewrites = search_until_useful("vague", retries=2)
    assert rewrites == 2


def _result(passages):
    from copilot.agents.tools.lookup_vulnerabilities import LookupResult

    return LookupResult(passages=passages)
