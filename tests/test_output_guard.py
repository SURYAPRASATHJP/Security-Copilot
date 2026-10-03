from pydantic import BaseModel

from copilot.guardrails.output_guard import (
    check_citations,
    check_matches_schema,
    check_no_secrets,
    check_versions_exist,
    guard_output,
)


class Answer(BaseModel):
    answer: str
    confidence: float


def known(package: str) -> frozenset[str]:
    return {
        "requests": frozenset({"2.27.1", "2.31.0", "2.33.0"}),
        "flask": frozenset({"2.2.2", "3.1.3"}),
    }.get(package, frozenset())


def test_a_citation_that_was_retrieved_is_allowed():
    assert check_citations(["GHSA-a"], ["GHSA-a", "GHSA-b"]) == []


def test_a_citation_that_was_never_retrieved_is_caught():
    findings = check_citations(["GHSA-invented"], ["GHSA-a"])
    assert len(findings) == 1
    assert "was not in the retrieved advisories" in findings[0].detail


def test_each_kind_of_credential_is_recognised():
    samples = [
        "gsk_" + "a" * 30,
        "sk-" + "b" * 30,
        "ghp_" + "c" * 30,
        "github_pat_" + "d" * 30,
        "hf_" + "e" * 30,
        "AKIAABCDEFGHIJKLMNOP",
        "-----BEGIN RSA PRIVATE KEY-----",
    ]
    for sample in samples:
        assert check_no_secrets(f"the value is {sample} ok") != [], sample


def test_ordinary_prose_contains_no_secrets():
    assert check_no_secrets("Upgrade requests to 2.31.0 to fix GHSA-j8r2-6x86-q33q.") == []


def test_a_version_that_pypi_serves_is_allowed():
    assert check_versions_exist({"requests": "2.31.0"}, lookup=known) == []


def test_an_invented_version_is_caught():
    findings = check_versions_exist({"requests": "9.9.9"}, lookup=known)
    assert "PyPI has no requests 9.9.9" in findings[0].detail


def test_a_package_pypi_does_not_know_is_reported_rather_than_waved_through():
    findings = check_versions_exist({"made-up-package": "1.0.0"}, lookup=known)
    assert "could not confirm" in findings[0].detail


def test_a_reply_matching_its_schema_passes():
    assert check_matches_schema('{"answer": "2.31.0", "confidence": 0.9}', Answer) == []


def test_a_reply_missing_a_field_is_caught():
    assert check_matches_schema('{"answer": "2.31.0"}', Answer) != []


def test_a_reply_that_is_not_json_is_caught():
    assert check_matches_schema("not json at all", Answer) != []


def test_a_clean_output_passes_every_check():
    result = guard_output(
        text="Upgrade requests to 2.31.0.",
        citations=["GHSA-j8r2"],
        allowed_citations=["GHSA-j8r2"],
        upgrades={"requests": "2.31.0"},
        payload='{"answer": "ok", "confidence": 1.0}',
        schema=Answer,
        lookup=known,
    )
    assert result.allowed is True
    assert result.summary == "every output check passed"


def test_every_problem_is_reported_not_just_the_first():
    result = guard_output(
        text="my key is gsk_" + "a" * 30,
        citations=["GHSA-invented"],
        allowed_citations=["GHSA-real"],
        upgrades={"requests": "9.9.9"},
        lookup=known,
    )
    assert result.allowed is False
    assert {finding.check for finding in result.findings} == {"secret", "citation", "version"}
    assert result.blocked_by("secret") is True
    assert result.blocked_by("schema") is False


def test_no_upgrades_means_no_version_lookup():
    def explode(package):
        raise AssertionError("PyPI should not be asked when nothing is being upgraded")

    assert guard_output(text="all fine", lookup=explode).allowed is True
