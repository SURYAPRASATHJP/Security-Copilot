import json

import pytest

from copilot import llm_client
from copilot.rag import route_question
from copilot.rag.route_question import answer_routed, wants_dependency_check


@pytest.mark.parametrize(
    "question",
    [
        "Am I affected by this?",
        "Are we vulnerable to it?",
        "Do my dependencies have any known problems?",
        "Which of our packages should I upgrade first?",
        "Check my requirements.txt please",
        "Is anything in my project at risk?",
    ],
)
def test_questions_about_the_users_own_packages_take_the_check_path(question):
    assert wants_dependency_check(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is CVE-2023-32681 about?",
        "Which version of requests fixes GHSA-j8r2-6x86-q33q?",
        "Is jinja2==3.1.2 affected by GHSA-h5c8-rqwp-cp95?",
        "Explain the urllib3 redirect problem",
    ],
)
def test_general_questions_go_straight_to_search(question):
    assert wants_dependency_check(question) is False


@pytest.fixture
def canned(monkeypatch):
    def fake_ask_llm(messages, json_schema=None, temperature=0, **kwargs):
        return json.dumps(
            {
                "answer": "Upgrade to 2.31.0.",
                "citations": [],
                "affected_packages": [],
                "confidence": 0.9,
            }
        )

    monkeypatch.setattr(llm_client, "ask_llm", fake_ask_llm)


def test_the_check_path_runs_the_dependency_check_first(canned, monkeypatch, tmp_path):
    called = {}

    class FakeReport:
        findings = []

    def fake_check(path):
        called["path"] = path
        return FakeReport()

    monkeypatch.setattr(route_question, "check_requirements_file", fake_check)
    monkeypatch.setattr(route_question, "answer_question", lambda *a, **k: "answered")

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.27.1\n")
    assert answer_routed("Am I affected?", requirements) == "answered"
    assert called["path"] == requirements


def test_the_search_path_never_runs_the_dependency_check(canned, monkeypatch):
    def fail(path):
        raise AssertionError("the dependency check should not run for a general question")

    monkeypatch.setattr(route_question, "check_requirements_file", fail)
    monkeypatch.setattr(route_question, "answer_question", lambda *a, **k: "answered")
    assert answer_routed("What is CVE-2023-32681 about?") == "answered"


def test_a_check_question_with_no_file_falls_back_to_search(canned, monkeypatch):
    def fail(path):
        raise AssertionError("there is no requirements file to check")

    monkeypatch.setattr(route_question, "check_requirements_file", fail)
    monkeypatch.setattr(route_question, "answer_question", lambda *a, **k: "answered")
    assert answer_routed("Am I affected?") == "answered"
