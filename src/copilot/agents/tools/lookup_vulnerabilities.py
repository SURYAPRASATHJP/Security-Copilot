from functools import lru_cache

import httpx
from pydantic import BaseModel, Field

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.dependencies.check_my_dependencies import (
    Finding,
    check_requirements,
    index_local_advisories,
)
from copilot.dependencies.read_requirements_file import ParsedRequirement, RequirementsFile
from copilot.rag.hybrid_search import hybrid_search
from copilot.rag.rerank_results import rerank_results
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import STRUCTURED
from copilot.settings import get_settings

CANDIDATES = 20
# A repository can have dozens of findings, and an agent only needs the worst few.
DEFAULT_FINDING_LIMIT = 10


class LookupRequest(BaseModel):
    packages: list[ParsedRequirement] = Field(default_factory=list)
    question: str | None = Field(
        default=None, description="Optional free text to search the advisory corpus with."
    )
    passages: int = 5
    limit: int = Field(
        default=DEFAULT_FINDING_LIMIT, description="Keep only this many findings, worst first."
    )


class LookupResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    findings_total: int = 0
    packages_checked: int = 0
    affected_packages: list[str] = Field(default_factory=list)
    passages: list[SearchResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@lru_cache
def local_advisory_index() -> dict[tuple[str, str], Advisory]:
    path = get_settings().data_dir / "processed" / "advisories.jsonl"
    return index_local_advisories(read_advisories(path))


def lookup_vulnerabilities(request: LookupRequest) -> LookupResult:
    """Read only. Check packages against OSV and optionally search the advisory corpus."""
    result = LookupResult()

    if request.packages:
        parsed = RequirementsFile(requirements=list(request.packages))
        with httpx.Client(timeout=60.0) as client:
            report = check_requirements(parsed, local_advisory_index(), client)
        result.findings_total = len(report.findings)
        result.findings = report.findings[: request.limit] if request.limit else report.findings
        result.packages_checked = report.packages_checked
        result.affected_packages = report.affected_packages
        result.warnings = report.warnings

    if request.question:
        candidates = hybrid_search(request.question, STRUCTURED, CANDIDATES)
        result.passages = rerank_results(request.question, candidates, request.passages)

    return result
