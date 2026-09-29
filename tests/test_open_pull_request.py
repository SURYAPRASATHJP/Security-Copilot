import subprocess

import pytest

from copilot.agents.tools import open_pull_request as module
from copilot.agents.tools.open_pull_request import (
    PullRequestRequest,
    build_body,
    check_target_is_allowed,
    findings_table,
    format_test_results,
    github_token,
    open_pull_request,
)
from copilot.agents.tools.run_project_tests import ProjectTestResult
from copilot.agents.tools.update_requirements_file import RefusedError
from copilot.dependencies.check_my_dependencies import Finding

FINDING = Finding(
    package="requests",
    canonical_name="requests",
    installed_version="2.27.1",
    advisory_id="GHSA-j8r2",
    fixed_version="2.31.0",
    cvss_score=6.1,
    epss_probability=0.0297,
    known_exploited=True,
)


def test_a_pull_request_from_main_is_refused():
    for branch in ("main", "master", "develop"):
        with pytest.raises(RefusedError, match="refusing to open"):
            check_target_is_allowed(branch, "main")


def test_a_branch_equal_to_its_base_is_refused():
    with pytest.raises(RefusedError, match="different from its base"):
        check_target_is_allowed("release", "release")


def test_a_fix_branch_against_main_is_allowed():
    check_target_is_allowed("security-copilot/fix-dependencies", "main")


def test_the_findings_table_links_every_advisory_to_osv():
    table = findings_table([FINDING])
    assert "[GHSA-j8r2](https://osv.dev/vulnerability/GHSA-j8r2)" in table
    assert "| requests | 2.27.1 |" in table
    assert table.strip().endswith("| yes |")


def test_an_empty_findings_list_says_so():
    assert "No findings" in findings_table([])


def test_a_finding_without_scores_leaves_those_cells_blank():
    bare = FINDING.model_copy(update={"cvss_score": None, "epss_probability": None})
    row = findings_table([bare]).splitlines()[-1]
    assert "|  |  |" in row


def test_the_test_section_reports_a_pass():
    section = format_test_results(ProjectTestResult(passed=True, output_tail=["6 passed"]))
    assert "tests passed against the upgraded pins" in section
    assert "6 passed" in section


def test_the_test_section_reports_a_failure():
    section = format_test_results(ProjectTestResult(passed=False, output_tail=["1 failed"]))
    assert "did not pass" in section


def test_the_test_section_says_when_nothing_ran():
    assert format_test_results(None) == "The test suite was not run."


def test_the_body_carries_every_section():
    body = build_body([FINDING], ["requests 2.27.1 to 2.31.0"], ProjectTestResult(passed=True))
    for heading in ("## What this changes", "## Why", "## Tests", "## Advisories cited"):
        assert heading in body
    assert "requests 2.27.1 to 2.31.0" in body


def test_a_body_with_no_upgrades_says_nothing_changed():
    assert "Nothing changed." in build_body([], [], None)


def test_a_missing_github_token_is_refused(monkeypatch):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="not logged in")

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(RefusedError, match="gh auth login"):
        github_token()


def test_a_present_github_token_is_returned(monkeypatch):
    def succeed(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="gho_example\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", succeed)
    assert github_token() == "gho_example"


def test_a_refused_target_never_reaches_github(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no token should be read for a refused target")

    monkeypatch.setattr(module, "github_token", fail)
    with pytest.raises(RefusedError):
        open_pull_request(
            PullRequestRequest(
                repository="owner/repo", branch="main", base="main", title="t", body="b"
            )
        )
