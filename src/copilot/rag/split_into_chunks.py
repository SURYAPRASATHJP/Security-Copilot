import argparse
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.settings import get_settings

FIXED = "fixed"
STRUCTURED = "structured"
WINDOW_TOKENS = 400
OVERLAP_TOKENS = 50


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: Sequence[int]) -> str: ...


class Chunk(BaseModel):
    chunk_id: str
    text: str
    strategy: str
    advisory_id: str
    package: str
    chunk_index: int
    cve_ids: list[str] = Field(default_factory=list)
    severity: str | None = None
    cvss_score: float | None = None
    epss_probability: float | None = None
    known_exploited: bool = False
    published: str | None = None


class EmbeddingTokenizer:
    """Counts and slices text in the tokens the embedding model actually sees."""

    def __init__(self, model_name: str) -> None:
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(model_name)

    def encode(self, text: str) -> list[int]:
        return self._tokenizer.encode(text, add_special_tokens=False)

    def decode(self, tokens: Sequence[int]) -> str:
        return self._tokenizer.decode(list(tokens), skip_special_tokens=True)


@lru_cache
def default_tokenizer() -> EmbeddingTokenizer:
    return EmbeddingTokenizer(get_settings().embedding_model_name)


def affected_range(advisory: Advisory) -> str:
    parts = []
    for version_range in advisory.ranges:
        introduced = version_range.introduced or "0"
        if version_range.fixed:
            parts.append(f">={introduced},<{version_range.fixed}")
        elif version_range.last_affected:
            parts.append(f">={introduced},<={version_range.last_affected}")
        else:
            parts.append(f">={introduced}")
    return " or ".join(parts) if parts else "not stated"


def context_header(advisory: Advisory) -> str:
    return f"Advisory {advisory.id} for package {advisory.package}:"


def summary_card(advisory: Advisory) -> str:
    """Return the short, self-contained description of an advisory used as its first chunk."""
    fixed = ", ".join(advisory.fixed_versions) if advisory.fixed_versions else "no fix listed"
    severity = advisory.severity or "unrated"
    if advisory.cvss_score is not None:
        severity = f"{severity} (CVSS {advisory.cvss_score})"
    epss = (
        f"{advisory.epss_probability:.5f}"
        if advisory.epss_probability is not None
        else "not scored"
    )
    aliases = ", ".join(advisory.aliases) if advisory.aliases else "none"

    return "\n".join(
        [
            context_header(advisory),
            f"Summary: {advisory.summary or 'no summary published'}",
            f"Affected versions: {affected_range(advisory)}",
            f"Fixed in: {fixed}",
            f"Severity: {severity}",
            f"Exploit probability (EPSS): {epss}",
            f"Known exploited: {'yes' if advisory.known_exploited else 'no'}",
            f"Aliases: {aliases}",
        ]
    )


def token_windows(
    text: str,
    tokenizer: Tokenizer,
    window: int = WINDOW_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[str]:
    """Slice text into overlapping token windows, keeping whole tokens."""
    tokens = tokenizer.encode(text)
    if not tokens:
        return []
    if len(tokens) <= window:
        return [text]

    # An overlap at or above the window would step backwards and never finish.
    step = max(1, window - min(overlap, window // 2))
    pieces = []
    for start in range(0, len(tokens), step):
        piece = tokens[start : start + window]
        if not piece:
            break
        pieces.append(tokenizer.decode(piece))
        if start + window >= len(tokens):
            break
    return pieces


def paragraphs(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def pack_paragraphs(blocks: Sequence[str], tokenizer: Tokenizer, window: int) -> list[str]:
    """Group paragraphs so each group stays under the window, splitting any oversized one."""
    packed: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for block in blocks:
        size = len(tokenizer.encode(block))
        if size > window:
            if current:
                packed.append("\n\n".join(current))
                current, current_tokens = [], 0
            packed.extend(token_windows(block, tokenizer, window))
            continue
        if current and current_tokens + size > window:
            packed.append("\n\n".join(current))
            current, current_tokens = [], 0
        current.append(block)
        current_tokens += size

    if current:
        packed.append("\n\n".join(current))
    return packed


def _chunk(advisory: Advisory, strategy: str, index: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{advisory.id}|{advisory.package}|{strategy}|{index}",
        text=text,
        strategy=strategy,
        advisory_id=advisory.id,
        package=advisory.package,
        chunk_index=index,
        cve_ids=advisory.cve_ids,
        severity=advisory.severity,
        cvss_score=advisory.cvss_score,
        epss_probability=advisory.epss_probability,
        known_exploited=advisory.known_exploited,
        published=advisory.published.date().isoformat() if advisory.published else None,
    )


def fixed_size_chunks(
    advisory: Advisory,
    tokenizer: Tokenizer,
    window: int = WINDOW_TOKENS,
    overlap: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk the advisory as one flat document, which is the naive baseline."""
    document = f"{advisory.id} {advisory.package}\n{advisory.summary}\n\n{advisory.details}".strip()
    windows = token_windows(document, tokenizer, window, overlap)
    return [_chunk(advisory, FIXED, index, text) for index, text in enumerate(windows)]


def structure_aware_chunks(
    advisory: Advisory, tokenizer: Tokenizer, window: int = WINDOW_TOKENS
) -> list[Chunk]:
    """Chunk the advisory as a summary card plus its details, each carrying a context header."""
    texts = [summary_card(advisory)]
    header = context_header(advisory)
    # The header is prepended afterwards, so it has to come out of the budget first.
    budget = max(1, window - len(tokenizer.encode(header)) - 1)
    for block in pack_paragraphs(paragraphs(advisory.details), tokenizer, budget):
        texts.append(f"{header}\n{block}")
    return [_chunk(advisory, STRUCTURED, index, text) for index, text in enumerate(texts)]


def write_chunks(chunks: Iterable[Chunk], path: Path) -> int:
    """Write chunks as JSON lines, refusing a set with a repeated id."""
    chunks = list(chunks)
    seen: set[str] = set()
    repeated = {c.chunk_id for c in chunks if c.chunk_id in seen or seen.add(c.chunk_id)}
    if repeated:
        # A repeated id means two advisories collided, and the vector store would reject it later.
        raise ValueError(f"{len(repeated)} repeated chunk ids, first {sorted(repeated)[0]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(chunk.model_dump_json() + "\n")
    return len(chunks)


def read_chunks(path: Path) -> list[Chunk]:
    with path.open(encoding="utf-8") as handle:
        return [Chunk.model_validate_json(line) for line in handle if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build both chunk sets from the merged records.")
    parser.add_argument("--window", type=int, default=WINDOW_TOKENS)
    parser.add_argument("--overlap", type=int, default=OVERLAP_TOKENS)
    args = parser.parse_args()

    settings = get_settings()
    processed = settings.data_dir / "processed"
    advisories = read_advisories(processed / "advisories.jsonl")
    tokenizer = default_tokenizer()

    fixed = [
        chunk
        for advisory in advisories
        for chunk in fixed_size_chunks(advisory, tokenizer, args.window, args.overlap)
    ]
    structured = [
        chunk
        for advisory in advisories
        for chunk in structure_aware_chunks(advisory, tokenizer, args.window)
    ]

    for strategy, chunks, filename in (
        (FIXED, fixed, "chunks_fixed.jsonl"),
        (STRUCTURED, structured, "chunks_structured.jsonl"),
    ):
        written = write_chunks(chunks, processed / filename)
        sizes = [len(tokenizer.encode(chunk.text)) for chunk in chunks]
        average = sum(sizes) / len(sizes) if sizes else 0
        print(
            f"{strategy}: {written} chunks from {len(advisories)} advisories, "
            f"mean {average:.0f} tokens, longest {max(sizes) if sizes else 0}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
