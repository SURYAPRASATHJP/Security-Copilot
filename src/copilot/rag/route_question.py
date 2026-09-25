import re
from pathlib import Path

from copilot.dependencies.check_my_dependencies import check_requirements_file
from copilot.rag.answer_with_citations import CitedAnswer, answer_question
from copilot.rag.split_into_chunks import STRUCTURED

OWN_PACKAGES = re.compile(
    r"\b(my|our|mine|ours|we|i)\b.{0,40}\b"
    r"(package|packages|dependency|dependencies|requirement|requirements|project|app|repo|stack)\b"
    r"|\b(am i|are we)\b.{0,20}\b(affected|vulnerable|at risk|exposed)\b"
    r"|\brequirements\.txt\b",
    re.IGNORECASE | re.DOTALL,
)


def wants_dependency_check(question: str) -> bool:
    """Return whether the question is about the user's own packages, not advisories at large."""
    return OWN_PACKAGES.search(question) is not None


def answer_routed(
    question: str,
    requirements_path: Path | None = None,
    strategy: str = STRUCTURED,
) -> CitedAnswer:
    """Check the user's own dependencies first when they asked about them, then answer."""
    if wants_dependency_check(question) and requirements_path is not None:
        report = check_requirements_file(requirements_path)
        return answer_question(question, findings=report.findings, strategy=strategy)
    return answer_question(question, strategy=strategy)
