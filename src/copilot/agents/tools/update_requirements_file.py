import difflib
import fnmatch
import subprocess
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pydantic import BaseModel, Field

from copilot.dependencies.read_requirements_file import (
    join_continuations,
    pinned_version,
    strip_noise,
)

ALLOWED_FILENAMES = "requirements*.txt"
PROTECTED_BRANCHES = {"main", "master", "trunk", "develop"}
GIT_TIMEOUT_SECONDS = 60


class RefusedError(RuntimeError):
    pass


class UpdateRequest(BaseModel):
    repo_path: str
    branch: str
    upgrades: dict[str, str] = Field(
        description="Package name to the version it should be pinned at."
    )
    requirements_path: str = "requirements.txt"


class UpdateResult(BaseModel):
    branch: str = ""
    file: str = ""
    changed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    diff: str = ""
    written: bool = False


def check_filename_is_allowed(requirements_path: str) -> None:
    if not fnmatch.fnmatch(Path(requirements_path).name, ALLOWED_FILENAMES):
        raise RefusedError(
            f"refusing to edit {requirements_path}, this tool only writes {ALLOWED_FILENAMES}"
        )


def check_branch_is_allowed(branch: str) -> None:
    if branch.strip().lower() in PROTECTED_BRANCHES:
        raise RefusedError(f"refusing to write to {branch}, changes go on a new branch")


def rewrite_pins(text: str, upgrades: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """Replace the pinned version on matching lines, leaving comments and markers alone."""
    wanted = {canonicalize_name(name): version for name, version in upgrades.items()}
    changed: list[str] = []
    unchanged = sorted(wanted)

    lines = text.splitlines(keepends=True)
    for number, joined in join_continuations(text):
        cleaned = strip_noise(joined)
        if not cleaned or cleaned.startswith("-"):
            continue
        try:
            requirement = Requirement(cleaned)
        except InvalidRequirement:
            continue

        name = canonicalize_name(requirement.name)
        new_version = wanted.get(name)
        if new_version is None:
            continue
        old_version = pinned_version(requirement)
        if old_version is None or old_version == new_version:
            continue

        index = number - 1
        if index < len(lines) and old_version in lines[index]:
            lines[index] = lines[index].replace(old_version, new_version, 1)
            changed.append(f"{requirement.name} {old_version} to {new_version}")
            if name in unchanged:
                unchanged.remove(name)

    return "".join(lines), changed, unchanged


def unified_diff(before: str, after: str, filename: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )


def create_branch(repo: Path, branch: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-B", branch],
        check=True,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def update_requirements_file(request: UpdateRequest, write: bool = True) -> UpdateResult:
    """Writes. Repin packages in a requirements file, on a new branch and nowhere else."""
    check_filename_is_allowed(request.requirements_path)
    check_branch_is_allowed(request.branch)

    repo = Path(request.repo_path).expanduser().resolve()
    target = repo / request.requirements_path
    if not target.is_file():
        raise RefusedError(f"{request.requirements_path} does not exist in {repo}")

    before = target.read_text(encoding="utf-8")
    after, changed, unchanged = rewrite_pins(before, request.upgrades)

    result = UpdateResult(
        branch=request.branch,
        file=request.requirements_path,
        changed=changed,
        unchanged=unchanged,
        diff=unified_diff(before, after, request.requirements_path),
    )
    if not changed or not write:
        return result

    create_branch(repo, request.branch)
    target.write_text(after, encoding="utf-8")
    result.written = True
    return result
