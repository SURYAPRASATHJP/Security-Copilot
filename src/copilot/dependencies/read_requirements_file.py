import re
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pydantic import BaseModel, Field

INLINE_COMMENT = re.compile(r"(?:^|\s)#.*$")
HASH_OPTION = re.compile(r"\s--hash=\S+")
INCLUDE_OPTIONS = ("-r", "--requirement", "-c", "--constraint")


class ParsedRequirement(BaseModel):
    name: str
    canonical_name: str
    specifier: str
    pinned_version: str | None = None
    extras: list[str] = Field(default_factory=list)
    marker: str | None = None
    line_number: int
    raw: str

    @property
    def is_pinned(self) -> bool:
        return self.pinned_version is not None


class RequirementsFile(BaseModel):
    path: str | None = None
    requirements: list[ParsedRequirement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def pinned(self) -> list[ParsedRequirement]:
        return [r for r in self.requirements if r.is_pinned]


def pinned_version(requirement: Requirement) -> str | None:
    """Return the exact version when the specifier pins one, otherwise None."""
    equals = [s for s in requirement.specifier if s.operator in ("==", "===")]
    if len(equals) != 1 or "*" in equals[0].version:
        return None
    return equals[0].version


def join_continuations(text: str) -> list[tuple[int, str]]:
    """Return (line number, line) pairs with backslash continuations folded together."""
    joined: list[tuple[int, str]] = []
    buffer = ""
    start_line = 1
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.rstrip()
        if not buffer:
            start_line = number
        if stripped.endswith("\\"):
            buffer += stripped[:-1].rstrip() + " "
            continue
        joined.append((start_line, (buffer + stripped).strip()))
        buffer = ""
    if buffer:
        joined.append((start_line, buffer.strip()))
    return joined


def strip_noise(line: str) -> str:
    without_hashes = HASH_OPTION.sub("", line)
    return INLINE_COMMENT.sub("", without_hashes).strip()


def read_requirements_text(text: str, path: str | None = None) -> RequirementsFile:
    """Parse the contents of a requirements file, warning instead of raising on odd lines."""
    parsed = RequirementsFile(path=path)
    # Windows editors and many exports prefix the file with a byte order mark.
    text = text.lstrip("\ufeff")

    for number, raw_line in join_continuations(text):
        line = strip_noise(raw_line)
        if not line:
            continue

        if line.startswith(INCLUDE_OPTIONS):
            parsed.warnings.append(
                f"line {number}: {line} points at another file, which is not followed"
            )
            continue
        if line.startswith("-"):
            # Everything else beginning with a dash is a pip option, not a package.
            continue

        try:
            requirement = Requirement(line)
        except InvalidRequirement as error:
            parsed.warnings.append(f"line {number}: cannot read {line!r} ({error})")
            continue

        version = pinned_version(requirement)
        if version is None:
            parsed.warnings.append(
                f"line {number}: {requirement.name} is not pinned to one version, "
                "so the check uses the newest version that matches"
            )

        parsed.requirements.append(
            ParsedRequirement(
                name=requirement.name,
                canonical_name=canonicalize_name(requirement.name),
                specifier=str(requirement.specifier),
                pinned_version=version,
                extras=sorted(requirement.extras),
                marker=str(requirement.marker) if requirement.marker else None,
                line_number=number,
                raw=line,
            )
        )

    return parsed


def read_requirements_file(path: Path) -> RequirementsFile:
    return read_requirements_text(path.read_text(encoding="utf-8"), path=str(path))
