import json
import re
from collections.abc import Callable, Sequence
from functools import lru_cache

import httpx
from packaging.utils import canonicalize_name
from pydantic import BaseModel, Field, ValidationError

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
VERSION_LOOKUP_TIMEOUT = 30.0

# Anything shaped like a real credential must never leave the system, whatever produced it.
SECRET_PATTERNS = {
    "a Groq key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    "an OpenAI key": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    "a GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    "a Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


class GuardFinding(BaseModel):
    check: str
    detail: str


class GuardResult(BaseModel):
    allowed: bool = True
    findings: list[GuardFinding] = Field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.allowed:
            return "every output check passed"
        return "; ".join(f"{f.check}: {f.detail}" for f in self.findings)

    def blocked_by(self, check: str) -> bool:
        return any(finding.check == check for finding in self.findings)


def check_citations(citations: Sequence[str], allowed: Sequence[str]) -> list[GuardFinding]:
    """Every cited id has to be one that was actually retrieved."""
    permitted = set(allowed)
    return [
        GuardFinding(check="citation", detail=f"{citation} was not in the retrieved advisories")
        for citation in citations
        if citation not in permitted
    ]


def check_no_secrets(text: str) -> list[GuardFinding]:
    return [
        GuardFinding(check="secret", detail=f"the output contains something shaped like {label}")
        for label, pattern in SECRET_PATTERNS.items()
        if pattern.search(text)
    ]


def check_matches_schema(payload: str, model: type[BaseModel]) -> list[GuardFinding]:
    try:
        model.model_validate_json(payload)
    except (ValidationError, json.JSONDecodeError) as error:
        return [GuardFinding(check="schema", detail=f"the reply did not match its schema: {error}")]
    return []


@lru_cache
def published_versions(package: str) -> frozenset[str]:
    """Ask PyPI what versions exist, so a suggested upgrade can be confirmed first."""
    try:
        response = httpx.get(
            PYPI_JSON_URL.format(package=package),
            timeout=VERSION_LOOKUP_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return frozenset()
    return frozenset((response.json().get("releases") or {}).keys())


VersionLookup = Callable[[str], frozenset[str]]


def check_versions_exist(
    upgrades: dict[str, str], lookup: VersionLookup = published_versions
) -> list[GuardFinding]:
    findings = []
    for package, version in sorted(upgrades.items()):
        known = lookup(canonicalize_name(package))
        if not known:
            findings.append(
                GuardFinding(
                    check="version",
                    detail=f"could not confirm {package} {version} exists on PyPI",
                )
            )
        elif version not in known:
            findings.append(
                GuardFinding(check="version", detail=f"PyPI has no {package} {version}")
            )
    return findings


def guard_output(
    text: str = "",
    citations: Sequence[str] = (),
    allowed_citations: Sequence[str] = (),
    upgrades: dict[str, str] | None = None,
    payload: str | None = None,
    schema: type[BaseModel] | None = None,
    lookup: VersionLookup = published_versions,
) -> GuardResult:
    """Run every check that has to hold before an answer or a change reaches anyone."""
    findings: list[GuardFinding] = []
    findings.extend(check_no_secrets(text))
    findings.extend(check_citations(citations, allowed_citations))
    if upgrades:
        findings.extend(check_versions_exist(upgrades, lookup))
    if payload is not None and schema is not None:
        findings.extend(check_matches_schema(payload, schema))
    return GuardResult(allowed=not findings, findings=findings)
