import subprocess
import tomllib
from pathlib import Path
from tempfile import mkdtemp

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pydantic import BaseModel, Field

from copilot.dependencies.read_requirements_file import (
    ParsedRequirement,
    read_requirements_file,
)

REQUIREMENTS_GLOB = "requirements*.txt"
PYPROJECT = "pyproject.toml"
SKIPPED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}
CLONE_TIMEOUT_SECONDS = 120


class ScanRequest(BaseModel):
    source: str = Field(description="A local path or a GitHub URL.")
    max_depth: int = Field(default=3, description="How deep to look for manifests.")


class ScanResult(BaseModel):
    source: str
    local_path: str
    manifests: list[str] = Field(default_factory=list)
    packages: list[ParsedRequirement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def package_names(self) -> list[str]:
        return sorted({package.canonical_name for package in self.packages})


def looks_like_a_url(source: str) -> bool:
    return source.startswith(("http://", "https://", "git@"))


def clone_repository(url: str, destination: Path) -> Path:
    """Make a shallow clone of a remote repository into a temporary folder."""
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(destination)],
        check=True,
        capture_output=True,
        timeout=CLONE_TIMEOUT_SECONDS,
    )
    return destination


def find_manifests(root: Path, max_depth: int = 3) -> list[Path]:
    """Return every requirements file and pyproject.toml, skipping vendored directories."""
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIPPED_DIRECTORIES for part in relative.parts):
            continue
        if len(relative.parts) > max_depth:
            continue
        if path.name == PYPROJECT or path.match(REQUIREMENTS_GLOB):
            found.append(path)
    return found


def requirement_strings_from_pyproject(data: dict) -> list[str]:
    project = data.get("project") or {}
    strings = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        strings.extend(extra)
    for group in (data.get("dependency-groups") or {}).values():
        strings.extend(entry for entry in group if isinstance(entry, str))
    return strings


def packages_from_pyproject(path: Path) -> tuple[list[ParsedRequirement], list[str]]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        return [], [f"{path.name}: cannot be read ({error})"]

    packages = []
    warnings = []
    for line_number, text in enumerate(requirement_strings_from_pyproject(data), start=1):
        try:
            requirement = Requirement(text)
        except InvalidRequirement as error:
            warnings.append(f"{path.name}: cannot read {text!r} ({error})")
            continue
        equals = [s for s in requirement.specifier if s.operator in ("==", "===")]
        pinned = equals[0].version if len(equals) == 1 and "*" not in equals[0].version else None
        packages.append(
            ParsedRequirement(
                name=requirement.name,
                canonical_name=canonicalize_name(requirement.name),
                specifier=str(requirement.specifier),
                pinned_version=pinned,
                extras=sorted(requirement.extras),
                marker=str(requirement.marker) if requirement.marker else None,
                line_number=line_number,
                raw=text,
            )
        )
    return packages, warnings


def scan_repository(request: ScanRequest) -> ScanResult:
    """Read only. Find every dependency manifest in a repository and return its packages."""
    if looks_like_a_url(request.source):
        root = clone_repository(request.source, Path(mkdtemp(prefix="copilot-scan-")) / "repo")
    else:
        root = Path(request.source).expanduser().resolve()

    result = ScanResult(source=request.source, local_path=str(root))
    if not root.is_dir():
        result.warnings.append(f"{root} is not a directory")
        return result

    manifests = find_manifests(root, request.max_depth)
    if not manifests:
        result.warnings.append("no requirements file or pyproject.toml was found")
        return result

    seen: set[tuple[str, str]] = set()
    for manifest in manifests:
        result.manifests.append(str(manifest.relative_to(root)))
        if manifest.name == PYPROJECT:
            packages, warnings = packages_from_pyproject(manifest)
        else:
            parsed = read_requirements_file(manifest)
            packages, warnings = parsed.requirements, parsed.warnings

        for package in packages:
            key = (package.canonical_name, package.pinned_version or package.specifier)
            if key not in seen:
                seen.add(key)
                result.packages.append(package)
        result.warnings.extend(f"{manifest.relative_to(root)}: {w}" for w in warnings)

    return result
