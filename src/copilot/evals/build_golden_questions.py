import argparse
import random
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.dependencies.version_ranges import (
    a_safe_version,
    an_affected_version,
    is_version_affected,
)
from copilot.settings import get_settings

FIXED_VERSION = "fixed_version"
IS_AFFECTED = "is_affected"
WHAT_IS = "what_is"
UNANSWERABLE = "unanswerable"

RETRIEVAL = "retrieval"
ANSWER = "answer"

REFUSAL = "refuse"

ANSWERABLE_TARGET = 200
ANSWER_SUITE_ANSWERABLE = 30
UNANSWERABLE_TARGET = 20

FAKE_PREFIXES = ("quantum", "turbo", "hyper", "nano", "omni")
FAKE_SUFFIXES = ("auth", "shield", "proxy", "cache", "router")


class GoldenQuestion(BaseModel):
    question_id: str
    question: str
    kind: str
    expected_answer: str
    expected_advisory_ids: list[str] = Field(default_factory=list)
    package: str | None = None
    answerable: bool = True
    suites: list[str] = Field(default_factory=list)


def fixed_version_questions(advisories: Sequence[Advisory], count: int) -> list[GoldenQuestion]:
    """Ask which version fixes an advisory, where the advisory itself holds the answer."""
    questions = []
    for advisory in advisories:
        answer = a_safe_version(advisory)
        if answer is None:
            continue
        questions.append(
            GoldenQuestion(
                question_id=f"{FIXED_VERSION}:{advisory.id}:{advisory.package}",
                question=f"Which version of {advisory.package} fixes {advisory.id}?",
                kind=FIXED_VERSION,
                expected_answer=answer,
                expected_advisory_ids=advisory.all_ids,
                package=advisory.package,
            )
        )
        if len(questions) == count:
            break
    return questions


def is_affected_questions(advisories: Sequence[Advisory], count: int) -> list[GoldenQuestion]:
    """Ask whether a concrete pin is affected, alternating between a yes and a no."""
    questions: list[GoldenQuestion] = []
    for advisory in advisories:
        wanted_yes = len(questions) % 2 == 0
        version = an_affected_version(advisory) if wanted_yes else a_safe_version(advisory)
        if version is None:
            continue
        affected = is_version_affected(advisory, version)
        if affected is not wanted_yes:
            continue
        questions.append(
            GoldenQuestion(
                question_id=f"{IS_AFFECTED}:{advisory.id}:{advisory.package}:{version}",
                question=f"Is {advisory.package}=={version} affected by {advisory.id}?",
                kind=IS_AFFECTED,
                expected_answer="yes" if affected else "no",
                expected_advisory_ids=advisory.all_ids,
                package=advisory.package,
            )
        )
        if len(questions) == count:
            break
    return questions


def what_is_questions(advisories: Sequence[Advisory], count: int) -> list[GoldenQuestion]:
    """Ask what a CVE is about, where the advisory summary is the known answer."""
    questions = []
    for advisory in advisories:
        if not advisory.cve_ids or not advisory.summary:
            continue
        cve = advisory.cve_ids[0]
        questions.append(
            GoldenQuestion(
                question_id=f"{WHAT_IS}:{cve}:{advisory.package}",
                question=f"What is {cve} about?",
                kind=WHAT_IS,
                expected_answer=advisory.summary,
                expected_advisory_ids=advisory.all_ids,
                package=advisory.package,
            )
        )
        if len(questions) == count:
            break
    return questions


def fake_package_names(count: int, taken: set[str], rng: random.Random) -> list[str]:
    names: list[str] = []
    bases = ["flask", "requests", "pyyaml", "urllib3", "jinja2", "boto3", "pandas", "numpy"]
    while len(names) < count:
        candidate = f"{rng.choice(bases)}-{rng.choice(FAKE_PREFIXES)}-{rng.choice(FAKE_SUFFIXES)}"
        if candidate not in taken and candidate not in names:
            names.append(candidate)
    return names


def fake_cve_ids(count: int, taken: set[str], rng: random.Random) -> list[str]:
    ids: list[str] = []
    while len(ids) < count:
        # Year 2099 keeps these clear of anything the real catalogues will ever publish.
        candidate = f"CVE-2099-{rng.randint(10000, 99999)}"
        if candidate not in taken and candidate not in ids:
            ids.append(candidate)
    return ids


def unanswerable_questions(
    count: int,
    known_packages: set[str],
    known_ids: set[str],
    real_packages: Sequence[str],
    rng: random.Random,
) -> list[GoldenQuestion]:
    """Ask about packages and CVE numbers that do not exist, so refusals can be measured."""
    packages = fake_package_names(count, known_packages, rng)
    cves = fake_cve_ids(count, known_ids, rng)

    templates = [
        lambda package, cve: f"Which version of {package} fixes {cve}?",
        lambda package, cve: f"Is {package}==1.0.0 affected by {cve}?",
        lambda package, cve: f"What is {cve} about?",
        lambda package, cve: f"Does {rng.choice(real_packages)} have an advisory called {cve}?",
    ]

    questions = []
    for index in range(count):
        package = packages[index]
        cve = cves[index]
        questions.append(
            GoldenQuestion(
                question_id=f"{UNANSWERABLE}:{index}",
                question=templates[index % len(templates)](package, cve),
                kind=UNANSWERABLE,
                expected_answer=REFUSAL,
                answerable=False,
                package=None,
                suites=[ANSWER],
            )
        )
    return questions


def assign_suites(answerable: Sequence[GoldenQuestion], answer_count: int) -> None:
    """Mark every answerable question for retrieval and a spread of them for answering too."""
    for question in answerable:
        question.suites = [RETRIEVAL]

    by_kind: dict[str, list[GoldenQuestion]] = {}
    for question in answerable:
        by_kind.setdefault(question.kind, []).append(question)

    per_kind = answer_count // len(by_kind) if by_kind else 0
    chosen = 0
    for questions in by_kind.values():
        for question in questions[:per_kind]:
            question.suites.append(ANSWER)
            chosen += 1
    for question in answerable:
        if chosen >= answer_count:
            break
        if ANSWER not in question.suites:
            question.suites.append(ANSWER)
            chosen += 1


def build_golden_questions(
    advisories: Sequence[Advisory], seed: int = 20260921
) -> list[GoldenQuestion]:
    rng = random.Random(seed)
    shuffled = list(advisories)
    rng.shuffle(shuffled)

    per_kind = ANSWERABLE_TARGET // 3
    answerable = [
        *fixed_version_questions(shuffled, per_kind),
        *is_affected_questions(shuffled, per_kind),
        *what_is_questions(shuffled, ANSWERABLE_TARGET - 2 * per_kind),
    ]
    assign_suites(answerable, ANSWER_SUITE_ANSWERABLE)

    known_packages = {advisory.package for advisory in advisories}
    known_ids = {identifier for advisory in advisories for identifier in advisory.all_ids}
    unanswerable = unanswerable_questions(
        UNANSWERABLE_TARGET, known_packages, known_ids, sorted(known_packages), rng
    )
    return [*answerable, *unanswerable]


def write_questions(questions: Sequence[GoldenQuestion], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for question in questions:
            handle.write(question.model_dump_json() + "\n")
    return len(questions)


def read_questions(path: Path) -> list[GoldenQuestion]:
    with path.open(encoding="utf-8") as handle:
        return [GoldenQuestion.model_validate_json(line) for line in handle if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the golden question set.")
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()

    settings = get_settings()
    advisories = read_advisories(settings.data_dir / "processed" / "advisories.jsonl")
    questions = build_golden_questions(advisories, args.seed)

    path = settings.data_dir / "eval" / "golden_questions.jsonl"
    write_questions(questions, path)

    counts: dict[str, int] = {}
    for question in questions:
        counts[question.kind] = counts.get(question.kind, 0) + 1
    retrieval = sum(1 for q in questions if RETRIEVAL in q.suites)
    answer = sum(1 for q in questions if ANSWER in q.suites)

    print(f"questions written: {len(questions)} to {path}")
    for kind, count in sorted(counts.items()):
        print(f"  {kind}: {count}")
    print(f"retrieval suite: {retrieval}")
    print(f"answer suite: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
