import subprocess

from copilot.agents.tools import run_project_tests as module
from copilot.agents.tools.run_project_tests import ProjectTestRequest, run_project_tests, tail_of


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def wire(monkeypatch, *, created=0, installed=0, run=None, timeout=False):
    monkeypatch.setattr(module, "create_environment", lambda d, v: completed(created))
    monkeypatch.setattr(module, "install_requirements", lambda d, r: completed(installed))

    def fake_run(*args, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(cmd="pytest", timeout=kwargs.get("timeout", 1))
        return run

    monkeypatch.setattr(module.subprocess, "run", fake_run)


def test_only_the_last_lines_of_output_are_kept():
    text = "\n".join(f"line {n}" for n in range(100))
    tail = tail_of(text, lines=5)
    assert tail == ["line 95", "line 96", "line 97", "line 98", "line 99"]


def test_blank_lines_are_dropped_from_the_tail():
    assert tail_of("one\n\n\ntwo\n") == ["one", "two"]


def test_a_missing_requirements_file_is_reported(tmp_path):
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path)))
    assert result.install_failed is True
    assert result.passed is False
    assert "was not found" in result.output_tail[0]


def test_a_passing_run_is_reported_as_passing(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    wire(monkeypatch, run=completed(0, stdout="6 passed in 1.2s"))
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path)))
    assert result.passed is True
    assert result.exit_code == 0
    assert result.summary == "tests passed"
    assert "6 passed" in result.output_tail[0]


def test_a_failing_run_is_reported_with_its_output(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    wire(monkeypatch, run=completed(1, stdout="1 failed, 5 passed\nassert 2 == 3"))
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path)))
    assert result.passed is False
    assert result.exit_code == 1
    assert result.summary == "tests failed"
    assert "1 failed, 5 passed" in result.output_tail


def test_an_upgrade_that_will_not_install_is_separated_from_a_test_failure(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==999.0.0\n")
    wire(monkeypatch, installed=1, run=completed(0))
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path)))
    assert result.install_failed is True
    assert result.passed is False
    assert result.summary == "the upgraded requirements could not be installed"


def test_an_environment_that_cannot_be_created_is_reported(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    wire(monkeypatch, created=1, run=completed(0))
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path)))
    assert result.install_failed is True


def test_a_run_that_never_finishes_is_stopped_and_said_so(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    wire(monkeypatch, timeout=True)
    result = run_project_tests(ProjectTestRequest(repo_path=str(tmp_path), timeout_seconds=30))
    assert result.timed_out is True
    assert result.passed is False
    assert "did not finish within 30 seconds" in result.summary


def test_the_time_taken_is_always_recorded(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    wire(monkeypatch, run=completed(0, stdout="ok"))
    assert run_project_tests(ProjectTestRequest(repo_path=str(tmp_path))).seconds > 0
