import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from copilot.settings import get_settings

DISMISSED = "dismissed"
BROKE_TESTS = "broke tests"

SCHEMA = """
CREATE TABLE IF NOT EXISTS repository_memory (
    repository TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    recorded_at REAL NOT NULL,
    PRIMARY KEY (repository, kind, subject)
)
"""


class Remembered(BaseModel):
    repository: str
    kind: str
    subject: str
    detail: str = ""
    recorded_at: float = 0.0


class RepositoryMemory(BaseModel):
    """What the agent learned about one repository on earlier runs."""

    dismissed_advisories: list[str] = Field(default_factory=list)
    upgrades_that_broke_tests: dict[str, str] = Field(default_factory=dict)

    def should_skip_advisory(self, advisory_id: str) -> bool:
        return advisory_id in self.dismissed_advisories

    def should_avoid_upgrade(self, package: str, version: str) -> bool:
        return self.upgrades_that_broke_tests.get(package) == version

    def as_prompt_note(self) -> str:
        """Return a short note the supervisor can put in front of the model, or nothing."""
        lines = []
        if self.dismissed_advisories:
            lines.append(
                "The user has already dismissed these advisories, so do not raise them again: "
                + ", ".join(sorted(self.dismissed_advisories))
            )
        for package, version in sorted(self.upgrades_that_broke_tests.items()):
            lines.append(f"Upgrading {package} to {version} broke the tests before, so avoid it.")
        return "\n".join(lines)


def memory_path() -> Path:
    return get_settings().data_dir / "agent_memory.sqlite"


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or memory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.execute(SCHEMA)
    connection.commit()
    return connection


def remember(
    connection: sqlite3.Connection, repository: str, kind: str, subject: str, detail: str = ""
) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO repository_memory VALUES (?, ?, ?, ?, ?)",
        (repository, kind, subject, detail, time.time()),
    )
    connection.commit()


def forget(connection: sqlite3.Connection, repository: str, kind: str, subject: str) -> None:
    connection.execute(
        "DELETE FROM repository_memory WHERE repository = ? AND kind = ? AND subject = ?",
        (repository, kind, subject),
    )
    connection.commit()


def rows_for(connection: sqlite3.Connection, repository: str) -> list[Remembered]:
    cursor = connection.execute(
        "SELECT repository, kind, subject, detail, recorded_at "
        "FROM repository_memory WHERE repository = ? ORDER BY recorded_at",
        (repository,),
    )
    return [
        Remembered(
            repository=row[0], kind=row[1], subject=row[2], detail=row[3], recorded_at=row[4]
        )
        for row in cursor.fetchall()
    ]


def recall(connection: sqlite3.Connection, repository: str) -> RepositoryMemory:
    """Load everything remembered about a repository into one object the supervisor can read."""
    memory = RepositoryMemory()
    for row in rows_for(connection, repository):
        if row.kind == DISMISSED:
            memory.dismissed_advisories.append(row.subject)
        elif row.kind == BROKE_TESTS:
            memory.upgrades_that_broke_tests[row.subject] = row.detail
    return memory


def dismiss_advisory(connection: sqlite3.Connection, repository: str, advisory_id: str) -> None:
    remember(connection, repository, DISMISSED, advisory_id)


def record_broken_upgrade(
    connection: sqlite3.Connection, repository: str, package: str, version: str
) -> None:
    remember(connection, repository, BROKE_TESTS, package, version)


def filter_findings(findings: Sequence[dict], memory: RepositoryMemory) -> list[dict]:
    """Drop findings the user already said they do not care about."""
    return [
        finding
        for finding in findings
        if not memory.should_skip_advisory(finding.get("advisory_id", ""))
    ]


def short_term_checkpointer(path: Path | None = None):  # noqa: ANN201
    """Return the LangGraph checkpointer that lets a crashed scan resume where it stopped."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    target = path or (get_settings().data_dir / "agent_checkpoints.sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(str(target), check_same_thread=False))
