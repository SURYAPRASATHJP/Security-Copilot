import re
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import mkdtemp

from pydantic import BaseModel, Field

DEFAULT_TIMEOUT_SECONDS = 300
OUTPUT_TAIL_LINES = 30
INSTALL_TIMEOUT_SECONDS = 600

# pytest colours its output, and those escape codes end up in pull request bodies.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class ProjectTestRequest(BaseModel):
    repo_path: str
    requirements_path: str = "requirements.txt"
    test_path: str = "tests"
    python_version: str = "3.11"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class ProjectTestResult(BaseModel):
    passed: bool = False
    exit_code: int | None = None
    timed_out: bool = False
    install_failed: bool = False
    seconds: float = 0.0
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    output_tail: list[str] = Field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.install_failed:
            return "the upgraded requirements could not be installed"
        if self.timed_out:
            return f"the tests did not finish within {self.timeout_seconds} seconds"
        return "tests passed" if self.passed else "tests failed"


def tail_of(text: str, lines: int = OUTPUT_TAIL_LINES) -> list[str]:
    plain = ANSI.sub("", text)
    return [line for line in plain.splitlines() if line.strip()][-lines:]


def create_environment(directory: Path, python_version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "venv", "--python", python_version, str(directory)],
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
        check=False,
    )


def install_requirements(directory: Path, requirements: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(directory / "bin" / "python"),
            "-r",
            str(requirements),
            "pytest",
        ],
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
        check=False,
    )


def run_project_tests(request: ProjectTestRequest) -> ProjectTestResult:
    """Read only. Install the given requirements in a throwaway environment and run the tests."""
    started = time.perf_counter()
    repo = Path(request.repo_path).expanduser().resolve()
    requirements = repo / request.requirements_path
    result = ProjectTestResult(timeout_seconds=request.timeout_seconds)

    if not requirements.exists():
        result.install_failed = True
        result.output_tail = [f"{request.requirements_path} was not found in {repo}"]
        return result

    environment = Path(mkdtemp(prefix="copilot-tests-")) / "venv"
    try:
        created = create_environment(environment, request.python_version)
        if created.returncode != 0:
            result.install_failed = True
            result.output_tail = tail_of(created.stderr or created.stdout)
            return result

        installed = install_requirements(environment, requirements)
        if installed.returncode != 0:
            result.install_failed = True
            result.output_tail = tail_of(installed.stderr or installed.stdout)
            return result

        try:
            run = subprocess.run(
                [str(environment / "bin" / "python"), "-m", "pytest", request.test_path, "-q"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            result.timed_out = True
            result.output_tail = [f"no result within {request.timeout_seconds} seconds"]
            return result

        result.exit_code = run.returncode
        result.passed = run.returncode == 0
        result.output_tail = tail_of(run.stdout + run.stderr)
        return result
    finally:
        result.seconds = time.perf_counter() - started
        shutil.rmtree(environment.parent, ignore_errors=True)
