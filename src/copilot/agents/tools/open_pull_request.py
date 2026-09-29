import subprocess
from collections.abc import Sequence

from pydantic import BaseModel, Field

from copilot.agents.tools.run_project_tests import ProjectTestResult
from copilot.agents.tools.update_requirements_file import (
    PROTECTED_BRANCHES,
    RefusedError,
)
from copilot.dependencies.check_my_dependencies import Finding

GH_TIMEOUT_SECONDS = 30
OSV_URL = "https://osv.dev/vulnerability/"


class PullRequestRequest(BaseModel):
    repository: str = Field(description="owner/name on GitHub.")
    branch: str
    base: str = "main"
    title: str
    body: str
    draft: bool = True


class PullRequestResult(BaseModel):
    url: str = ""
    number: int = 0
    draft: bool = True


def github_token() -> str:
    """Read the token the user already signed in with, so no key is stored by this project."""
    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        check=False,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise RefusedError("no GitHub token is available, run gh auth login first")
    return token


def check_target_is_allowed(branch: str, base: str) -> None:
    if branch.strip().lower() in PROTECTED_BRANCHES:
        raise RefusedError(f"refusing to open a pull request from {branch}")
    if branch.strip() == base.strip():
        raise RefusedError("a pull request needs a branch different from its base")


def findings_table(findings: Sequence[Finding]) -> str:
    if not findings:
        return "No findings were left to report."
    lines = [
        "| Package | Installed | Advisory | Fixed in | CVSS | EPSS | Known exploited |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for finding in findings:
        epss = f"{finding.epss_probability:.5f}" if finding.epss_probability is not None else ""
        cvss = finding.cvss_score if finding.cvss_score is not None else ""
        lines.append(
            f"| {finding.package} | {finding.installed_version or 'unpinned'} | "
            f"[{finding.advisory_id}]({OSV_URL}{finding.advisory_id}) | "
            f"{finding.fixed_version or 'no fix listed'} | "
            f"{cvss} | {epss} | "
            f"{'yes' if finding.known_exploited else 'no'} |"
        )
    return "\n".join(lines)


def format_test_results(result: ProjectTestResult | None) -> str:
    if result is None:
        return "The test suite was not run."
    status = "passed" if result.passed else "did not pass"
    lines = [f"The project's own tests {status} against the upgraded pins.", ""]
    if result.output_tail:
        lines.extend(["```", *result.output_tail[-12:], "```"])
    return "\n".join(lines)


def build_body(
    findings: Sequence[Finding],
    upgrades: Sequence[str],
    tests: ProjectTestResult | None = None,
) -> str:
    """Write the pull request body: what was found, what changed, and whether the tests held."""
    citations = sorted({finding.advisory_id for finding in findings})
    return "\n\n".join(
        [
            "## What this changes",
            "\n".join(f"- {line}" for line in upgrades) if upgrades else "- Nothing changed.",
            "## Why",
            findings_table(findings),
            "## Tests",
            format_test_results(tests),
            "## Advisories cited",
            " ".join(f"[{cid}]({OSV_URL}{cid})" for cid in citations) if citations else "None.",
        ]
    )


def open_pull_request(request: PullRequestRequest) -> PullRequestResult:
    """Writes. Open a pull request from a fix branch, never against the base branch itself."""
    check_target_is_allowed(request.branch, request.base)

    from github import Github

    client = Github(github_token())
    repository = client.get_repo(request.repository)
    pull = repository.create_pull(
        title=request.title,
        body=request.body,
        head=request.branch,
        base=request.base,
        draft=request.draft,
    )
    return PullRequestResult(url=pull.html_url, number=pull.number, draft=request.draft)
