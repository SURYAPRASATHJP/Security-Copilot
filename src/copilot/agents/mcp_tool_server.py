from mcp.server.fastmcp import FastMCP

from copilot.agents.tools.check_if_code_uses_package import (
    UsageRequest,
    check_if_code_uses_package,
)
from copilot.agents.tools.find_safe_version import SafeVersionRequest, find_safe_version
from copilot.agents.tools.lookup_vulnerabilities import LookupRequest, lookup_vulnerabilities
from copilot.agents.tools.open_pull_request import PullRequestRequest, open_pull_request
from copilot.agents.tools.run_project_tests import ProjectTestRequest, run_project_tests
from copilot.agents.tools.scan_repository import ScanRequest, scan_repository
from copilot.agents.tools.update_requirements_file import UpdateRequest, update_requirements_file

server = FastMCP("security-copilot")


@server.tool()
def scan_repository_for_packages(source: str, max_depth: int = 3) -> dict:
    """Read only. List every Python package a repository declares.

    Takes a local path or a GitHub URL, finds requirements*.txt and pyproject.toml, and
    returns each package with the version it is pinned at. Start here: every other tool
    needs the package list this returns.
    """
    return scan_repository(ScanRequest(source=source, max_depth=max_depth)).model_dump()


@server.tool()
def look_up_vulnerabilities(
    packages: list[dict], question: str | None = None, limit: int = 10
) -> dict:
    """Read only. Find the known vulnerabilities affecting a list of packages.

    Pass the packages returned by scan_repository_for_packages. Returns one finding per
    advisory, already ordered by what to fix first: on the CISA known exploited list,
    then exploit probability, then severity. An optional question also searches the
    advisory text. Only the worst `limit` findings come back, with the full count in
    findings_total, so keep the limit small and ask again if you need more.
    """
    request = LookupRequest.model_validate(
        {"packages": packages, "question": question, "limit": limit}
    )
    return lookup_vulnerabilities(request).model_dump()


@server.tool()
def check_if_code_uses_the_package(
    repo_path: str, package: str, advisory_text: str | None = None
) -> dict:
    """Read only. Decide whether the repository actually reaches a vulnerable package.

    Parses the code rather than guessing. Returns one of three verdicts: used, imported
    but the vulnerable function is not called, or not used, each with the file and line
    that proves it. Use this before ranking a finding as urgent, because a package that
    is never imported is rarely worth an upgrade.
    """
    request = UsageRequest(repo_path=repo_path, package=package, advisory_text=advisory_text)
    return check_if_code_uses_package(request).model_dump()


@server.tool()
def find_the_lowest_safe_version(
    package: str, current_version: str | None = None, advisory_ids: list[str] | None = None
) -> dict:
    """Read only. Find the lowest version on PyPI that fixes every advisory for a package.

    Only ever returns a version PyPI actually serves, so the answer can be pinned
    directly. Give the advisory ids when you only care about specific findings.
    """
    request = SafeVersionRequest(
        package=package, current_version=current_version, advisory_ids=advisory_ids or []
    )
    return find_safe_version(request).model_dump()


@server.tool()
def run_the_project_tests(
    repo_path: str, requirements_path: str = "requirements.txt", test_path: str = "tests"
) -> dict:
    """Read only. Install the given requirements in a throwaway environment and run the tests.

    Use this after proposing an upgrade and before asking for approval. It separates an
    upgrade that will not install from one that installs but breaks the tests, and returns
    the last lines of output either way.
    """
    request = ProjectTestRequest(
        repo_path=repo_path, requirements_path=requirements_path, test_path=test_path
    )
    return run_project_tests(request).model_dump()


@server.tool()
def update_the_requirements_file(
    repo_path: str,
    branch: str,
    upgrades: dict[str, str],
    requirements_path: str = "requirements.txt",
) -> dict:
    """Writes. Repin packages in a requirements file, on a new branch and nowhere else.

    Refuses any file that is not a requirements*.txt and refuses to write to main, master,
    trunk or develop. Returns the diff it produced. This changes files, so it needs human
    approval first.
    """
    request = UpdateRequest(
        repo_path=repo_path,
        branch=branch,
        upgrades=upgrades,
        requirements_path=requirements_path,
    )
    return update_requirements_file(request).model_dump()


@server.tool()
def open_a_pull_request(
    repository: str, branch: str, title: str, body: str, base: str = "main", draft: bool = True
) -> dict:
    """Writes. Open a pull request from a fix branch.

    Refuses to open one from a protected branch or against itself. Uses the GitHub login
    the user already has, so no token is stored by this project. This is visible to other
    people, so it needs human approval first.
    """
    request = PullRequestRequest(
        repository=repository, branch=branch, title=title, body=body, base=base, draft=draft
    )
    return open_pull_request(request).model_dump()


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
