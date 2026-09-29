from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
NOT_NEEDED = "not needed"


class PackageRisk(BaseModel):
    package: str
    installed_version: str | None = None
    advisory_id: str
    fixed_version: str | None = None
    usage: str = "unknown"
    rank: int = 0
    reason: str = ""


class TriageReport(BaseModel):
    repository: str
    packages_checked: int = 0
    findings_considered: int = 0
    ranked: list[PackageRisk] = Field(default_factory=list)
    notes: str = ""

    @property
    def worst_first(self) -> list[PackageRisk]:
        return sorted(self.ranked, key=lambda risk: risk.rank)


class AgentState(TypedDict, total=False):
    repository: str
    packages: list[dict]
    findings: list[dict]
    plan: list[str]
    upgrades: dict[str, str]
    test_results: dict | None
    approval: str
    report: dict | None
    branch: str
    pull_request_url: str
    steps: int
    messages: Annotated[list, add_messages]
