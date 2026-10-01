import pytest

from copilot.agents.human_approval import (
    APPROVED,
    EDITED,
    REJECTED,
    ApprovalDecision,
    NotApprovedError,
    PlannedChange,
    approval_from_terminal,
    approved_upgrades,
    assert_approved,
    is_write_tool,
)

CHANGE = PlannedChange(
    kind="update_requirements",
    repository="demo_vulnerable_app",
    branch="security-copilot/fix-dependencies",
    summary="Repin three packages",
    diff="-flask==2.2.2\n+flask==3.1.3\n",
    upgrades={"flask": "3.1.3", "requests": "2.33.0"},
)


def test_the_two_write_tools_are_the_ones_that_need_approval():
    assert is_write_tool("update_the_requirements_file") is True
    assert is_write_tool("open_a_pull_request") is True


def test_a_read_tool_needs_no_approval():
    for name in ("scan_repository_for_packages", "look_up_vulnerabilities", "unknown_tool"):
        assert is_write_tool(name) is False


def test_the_prompt_shows_the_branch_the_upgrades_and_the_diff():
    text = CHANGE.as_prompt()
    assert "security-copilot/fix-dependencies" in text
    assert "flask to 3.1.3" in text
    assert "requests to 2.33.0" in text
    assert "-flask==2.2.2" in text


def test_a_rejected_decision_blocks_the_write():
    with pytest.raises(NotApprovedError):
        assert_approved(ApprovalDecision(decision=REJECTED, reason="not now"))


def test_the_default_decision_is_to_reject():
    assert ApprovalDecision().allows_the_write is False


def test_an_approved_decision_allows_the_write():
    assert_approved(ApprovalDecision(decision=APPROVED))
    assert ApprovalDecision(decision=APPROVED).allows_the_write is True


def test_an_edited_decision_also_allows_the_write():
    assert ApprovalDecision(decision=EDITED).allows_the_write is True


def test_approval_writes_exactly_what_was_shown():
    decision = ApprovalDecision(decision=APPROVED)
    assert approved_upgrades(CHANGE, decision) == {"flask": "3.1.3", "requests": "2.33.0"}


def test_an_edit_replaces_what_gets_written():
    decision = ApprovalDecision(decision=EDITED, upgrades={"flask": "3.1.3"})
    assert approved_upgrades(CHANGE, decision) == {"flask": "3.1.3"}


def test_a_rejection_yields_nothing_to_write():
    with pytest.raises(NotApprovedError, match="changed my mind"):
        approved_upgrades(CHANGE, ApprovalDecision(decision=REJECTED, reason="changed my mind"))


def test_the_terminal_fallback_accepts_a_yes(capsys):
    decision = approval_from_terminal(CHANGE, read_line=lambda _: "y")
    assert decision.decision == APPROVED
    assert decision.upgrades == CHANGE.upgrades
    assert "security-copilot/fix-dependencies" in capsys.readouterr().out


def test_the_terminal_fallback_treats_anything_else_as_no(capsys):
    for answer in ("n", "no", "", "maybe"):
        decision = approval_from_terminal(CHANGE, read_line=lambda _, said=answer: said)
        assert decision.decision == REJECTED
