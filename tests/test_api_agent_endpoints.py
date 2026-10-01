import json

import pytest
from fastapi.testclient import TestClient

from api import main
from api.main import jsonable
from copilot.agents.agent_state import TriageReport


@pytest.fixture
def client():
    return TestClient(main.app)


def read_events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_a_pydantic_model_is_made_safe_for_the_wire():
    report = TriageReport(repository="demo", packages_checked=3)
    assert jsonable(report)["packages_checked"] == 3


def test_nested_models_and_lists_are_handled():
    value = {"items": [TriageReport(repository="a"), {"inner": TriageReport(repository="b")}]}
    rendered = jsonable(value)
    assert rendered["items"][0]["repository"] == "a"
    assert rendered["items"][1]["inner"]["repository"] == "b"


def test_something_that_cannot_be_serialised_becomes_its_text():
    assert jsonable({"when": object()})["when"].startswith("<object")


def test_a_scan_streams_a_step_for_every_node(client):
    response = client.post("/scan-repo", json={"repository": "fixtures/no_manifest"})
    assert response.status_code == 200
    events = read_events(response)
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "finished"
    assert {event["node"] for event in events if event["event"] == "step"} >= {
        "scanner",
        "analyst",
        "reviewer",
    }


def test_every_streamed_event_carries_the_thread_id(client):
    events = read_events(client.post("/scan-repo", json={"repository": "fixtures/no_manifest"}))
    thread_ids = {event["thread_id"] for event in events}
    assert len(thread_ids) == 1
    assert next(iter(thread_ids))


def test_a_caller_may_choose_the_thread_id(client):
    events = read_events(
        client.post(
            "/scan-repo", json={"repository": "fixtures/no_manifest", "thread_id": "mine-1"}
        )
    )
    assert all(event["thread_id"] == "mine-1" for event in events)


def test_a_scan_that_fails_streams_an_error_rather_than_dropping_the_connection(client):
    events = read_events(
        client.post("/scan-repo", json={"repository": "/does/not/exist", "thread_id": "bad-1"})
    )
    assert events[0]["event"] == "started"
    assert events[-1]["event"] in ("error", "finished")


def test_a_scan_of_a_repository_with_no_manifest_proposes_nothing(client):
    events = read_events(
        client.post("/scan-repo", json={"repository": "fixtures/no_manifest", "thread_id": "n-1"})
    )
    scanner = next(e for e in events if e.get("node") == "scanner")
    assert scanner["update"]["packages"] == []
    assert "no manifest" in scanner["update"]["plan"][0]


def test_an_unknown_decision_is_rejected(client):
    response = client.post("/approve", json={"thread_id": "t", "decision": "maybe"})
    assert response.status_code == 422
    assert "decision must be one of" in response.json()["detail"]


def test_an_approval_resumes_the_thread_it_names(client, monkeypatch):
    resumed = {}

    class FakeGraph:
        def invoke(self, command, config):
            resumed["thread_id"] = config["configurable"]["thread_id"]
            resumed["resume"] = command.resume
            return {"branch": "security-copilot/fix-dependencies", "upgrades": {"flask": "3.1.3"}}

    monkeypatch.setattr(main, "team_graph", lambda: FakeGraph())
    body = client.post(
        "/approve",
        json={"thread_id": "t-9", "decision": "approved", "upgrades": {"flask": "3.1.3"}},
    ).json()

    assert resumed["thread_id"] == "t-9"
    assert resumed["resume"]["decision"] == "approved"
    assert body["branch"] == "security-copilot/fix-dependencies"
    assert body["upgrades"] == {"flask": "3.1.3"}


def test_a_rejection_is_passed_through_with_its_reason(client, monkeypatch):
    seen = {}

    class FakeGraph:
        def invoke(self, command, config):
            seen.update(command.resume)
            return {}

    monkeypatch.setattr(main, "team_graph", lambda: FakeGraph())
    client.post("/approve", json={"thread_id": "t-10", "decision": "rejected", "reason": "not now"})
    assert seen["decision"] == "rejected"
    assert seen["reason"] == "not now"
