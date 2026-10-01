import shutil
import subprocess
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from copilot.agents.agent_state import AgentState
from copilot.agents.human_approval import APPROVED, EDITED, REJECTED
from copilot.agents.team_supervisor import (
    APPROVAL,
    FIX_BRANCH,
    WRITER,
    approval,
    route_after_approval,
    route_after_review_with_write,
    writer,
)

DEMO = Path(__file__).resolve().parents[1] / "demo_vulnerable_app"


def a_repository(tmp_path):
    """Copy the demo app into a throwaway git repository."""
    repo = tmp_path / "repo"
    shutil.copytree(DEMO, repo)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        check=True,
    )
    return repo


def approval_graph():
    graph = StateGraph(AgentState)
    graph.add_node(APPROVAL, approval)
    graph.add_node(WRITER, writer)
    graph.add_edge(START, APPROVAL)
    graph.add_conditional_edges(APPROVAL, route_after_approval, {WRITER: WRITER, END: END})
    graph.add_edge(WRITER, END)
    return graph.compile(checkpointer=MemorySaver())


def test_the_graph_stops_and_asks_before_writing_anything(tmp_path):
    repo = a_repository(tmp_path)
    before = (repo / "requirements.txt").read_text()
    team = approval_graph()
    config = {"configurable": {"thread_id": "t1"}}

    result = team.invoke(
        {"repository": str(repo), "upgrades": {"flask": "3.1.3"}, "steps": 0}, config
    )

    assert "__interrupt__" in result
    assert (repo / "requirements.txt").read_text() == before


def test_the_question_it_asks_carries_the_diff(tmp_path):
    repo = a_repository(tmp_path)
    team = approval_graph()
    result = team.invoke(
        {"repository": str(repo), "upgrades": {"flask": "3.1.3"}, "steps": 0},
        {"configurable": {"thread_id": "t2"}},
    )
    change = result["__interrupt__"][0].value["planned_change"]
    assert change["upgrades"] == {"flask": "3.1.3"}
    assert "-flask==2.2.2" in change["diff"]
    assert "+flask==3.1.3" in change["diff"]
    assert change["branch"] == FIX_BRANCH


def test_approving_writes_exactly_what_was_shown(tmp_path):
    repo = a_repository(tmp_path)
    team = approval_graph()
    config = {"configurable": {"thread_id": "t3"}}
    team.invoke({"repository": str(repo), "upgrades": {"flask": "3.1.3"}, "steps": 0}, config)

    team.invoke(Command(resume={"decision": APPROVED, "upgrades": {"flask": "3.1.3"}}), config)

    assert "flask==3.1.3" in (repo / "requirements.txt").read_text()
    branch = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch.stdout.strip() == FIX_BRANCH


def test_rejecting_writes_nothing(tmp_path):
    repo = a_repository(tmp_path)
    before = (repo / "requirements.txt").read_text()
    team = approval_graph()
    config = {"configurable": {"thread_id": "t4"}}
    team.invoke({"repository": str(repo), "upgrades": {"flask": "3.1.3"}, "steps": 0}, config)

    team.invoke(Command(resume={"decision": REJECTED, "reason": "not now"}), config)

    assert (repo / "requirements.txt").read_text() == before


def test_an_edited_approval_writes_only_what_was_edited_to(tmp_path):
    repo = a_repository(tmp_path)
    team = approval_graph()
    config = {"configurable": {"thread_id": "t5"}}
    team.invoke(
        {"repository": str(repo), "upgrades": {"flask": "3.1.3", "requests": "2.33.0"}, "steps": 0},
        config,
    )

    team.invoke(Command(resume={"decision": EDITED, "upgrades": {"flask": "3.1.3"}}), config)

    text = (repo / "requirements.txt").read_text()
    assert "flask==3.1.3" in text
    assert "requests==2.27.1" in text


def test_nothing_to_upgrade_never_asks_for_approval(tmp_path):
    repo = a_repository(tmp_path)
    update = approval({"repository": str(repo), "upgrades": {}, "steps": 0})
    assert update["approval"] == "not needed"


def test_the_writer_refuses_to_act_without_an_approval(tmp_path):
    repo = a_repository(tmp_path)
    before = (repo / "requirements.txt").read_text()
    update = writer(
        {"repository": str(repo), "upgrades": {"flask": "3.1.3"}, "approval": REJECTED, "steps": 0}
    )
    assert "branch" not in update
    assert (repo / "requirements.txt").read_text() == before


def test_routing_reaches_the_writer_only_after_an_approval():
    assert route_after_approval({"approval": APPROVED}) == WRITER
    assert route_after_approval({"approval": EDITED}) == WRITER
    assert route_after_approval({"approval": REJECTED}) == END
    assert route_after_approval({}) == END


def test_an_accepted_review_with_upgrades_goes_to_approval():
    state = {"review": {"accepted": True, "send_back": False}, "upgrades": {"flask": "3.1.3"}}
    assert route_after_review_with_write(state) == APPROVAL


def test_an_accepted_review_with_nothing_to_do_ends():
    assert route_after_review_with_write({"review": {"accepted": True}, "upgrades": {}}) == END


def test_a_review_that_sends_work_back_never_reaches_approval():
    state = {"review": {"send_back": True}, "upgrades": {"flask": "3.1.3"}}
    assert route_after_review_with_write(state) == "fixer"
