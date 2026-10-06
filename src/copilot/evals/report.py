from pathlib import Path

from copilot.settings import get_settings

REPORT_PATH = Path("docs/eval_report.md")

RETRIEVAL = "retrieval"
ANSWERS = "answers"
AGENTS = "agents"
COST = "cost"
RED_TEAM = "red_team"
LOAD = "load"
JUDGE = "judge"
MODELS = "models"
GAPS = "gaps"
RAGAS = "ragas"
ERRORS = "errors"

# The order the finished report reads in, whatever order the evals were run in.
SECTION_ORDER = (
    RETRIEVAL,
    ANSWERS,
    JUDGE,
    RAGAS,
    MODELS,
    AGENTS,
    RED_TEAM,
    ERRORS,
    COST,
    LOAD,
    GAPS,
)

HEADER = """# Evaluation report

Every number here comes from `make evals`. The golden set is generated from the advisory
corpus itself, so each answer is known without anyone labelling it. Each section is written
by the eval that produced it and assembled here, so a section is replaced when its eval is
re-run rather than appended to."""


def sections_dir() -> Path:
    return get_settings().data_dir / "eval" / "sections"


def section_path(name: str) -> Path:
    return sections_dir() / f"{name}.md"


def write_section(name: str, markdown: str) -> Path:
    """Replace one section, leaving the others as they were."""
    path = section_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown.strip() + "\n", encoding="utf-8")
    return path


def read_section(name: str) -> str:
    path = section_path(name)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def assemble(path: Path = REPORT_PATH) -> Path:
    """Build the report from whichever sections exist, in a fixed order."""
    parts = [HEADER]
    for name in SECTION_ORDER:
        body = read_section(name)
        if body:
            parts.append(body)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return path


def sections_present() -> list[str]:
    return [name for name in SECTION_ORDER if read_section(name)]
