from pydantic import BaseModel, Field

from copilot.agents.mcp_tools import WRITE_TOOLS

APPROVED = "approved"
REJECTED = "rejected"
EDITED = "edited"

UPDATE_REQUIREMENTS = "update_requirements"
OPEN_PULL_REQUEST = "open_pull_request"


class NotApprovedError(RuntimeError):
    pass


class PlannedChange(BaseModel):
    kind: str
    repository: str
    branch: str = ""
    summary: str = ""
    diff: str = ""
    upgrades: dict[str, str] = Field(default_factory=dict)

    def as_prompt(self) -> str:
        """Render the change the way a person needs to see it before saying yes."""
        lines = [f"{self.summary or self.kind} in {self.repository}"]
        if self.branch:
            lines.append(f"on branch {self.branch}")
        for package, version in sorted(self.upgrades.items()):
            lines.append(f"  {package} to {version}")
        if self.diff:
            lines.extend(["", self.diff.rstrip()])
        return "\n".join(lines)


class ApprovalDecision(BaseModel):
    decision: str = REJECTED
    reason: str = ""
    upgrades: dict[str, str] = Field(default_factory=dict)

    @property
    def allows_the_write(self) -> bool:
        return self.decision in (APPROVED, EDITED)


def write_allowed(approval: str) -> bool:
    """An edit is an approval of a changed set, so it permits the write too."""
    return approval in (APPROVED, EDITED)


def is_write_tool(tool_name: str) -> bool:
    return tool_name in WRITE_TOOLS


def request_approval(change: PlannedChange) -> ApprovalDecision:
    """Stop the graph and wait for a person. Resuming carries their decision back in."""
    from langgraph.types import interrupt

    answer = interrupt({"planned_change": change.model_dump()})
    return ApprovalDecision.model_validate(answer)


def approval_from_terminal(change: PlannedChange, read_line=input) -> ApprovalDecision:  # noqa: ANN001
    """Ask on the command line, for when there is no interface attached."""
    print(change.as_prompt())
    answer = read_line("Approve this change? [y]es, [n]o: ").strip().lower()
    if answer in ("y", "yes"):
        return ApprovalDecision(decision=APPROVED, upgrades=dict(change.upgrades))
    return ApprovalDecision(decision=REJECTED, reason="declined at the terminal")


def approved_upgrades(change: PlannedChange, decision: ApprovalDecision) -> dict[str, str]:
    """Return what may actually be written, which is the edited set when there is one."""
    assert_approved(decision)
    return decision.upgrades if decision.decision == EDITED else dict(change.upgrades)


def assert_approved(decision: ApprovalDecision) -> None:
    if not decision.allows_the_write:
        raise NotApprovedError(decision.reason or "the change was not approved")
