import argparse
import json
import time
from collections.abc import Sequence
from pathlib import Path

import httpx
from packaging.utils import canonicalize_name
from pydantic import BaseModel

from copilot.data_collection.advisory import Advisory, advisories_from_osv
from copilot.data_collection.fetch_exploit_signals import kev_cve_ids
from copilot.data_collection.merge_into_one_record import enrich, load_nvd_cache, read_advisories
from copilot.rag.build_search_index import (
    CHUNK_FILES,
    bm25_path,
    build_keyword_index,
    chroma_client,
    chunk_metadata,
    collection_name,
    embed_passages,
    load_embedder,
)
from copilot.rag.split_into_chunks import (
    FIXED,
    STRUCTURED,
    default_tokenizer,
    fixed_size_chunks,
    structure_aware_chunks,
    write_chunks,
)
from copilot.settings import get_settings

MODIFIED_IDS_URL = "https://storage.googleapis.com/osv-vulnerabilities/PyPI/modified_id.csv"
ADVISORY_URL = "https://api.osv.dev/v1/vulns/"
WATERMARK_FILE = "last_refresh.txt"


class RefreshReport(BaseModel):
    rows_in_feed: int = 0
    changed_since_watermark: int = 0
    in_scope: int = 0
    advisories_rebuilt: int = 0
    chunks_reembedded: int = 0
    seconds: float = 0.0
    new_watermark: str | None = None
    seeded: bool = False


def parse_feed(text: str) -> list[tuple[str, str]]:
    """Return (timestamp, advisory id) pairs from the modified ids feed, newest first."""
    rows = []
    for line in text.splitlines():
        timestamp, separator, advisory_id = line.partition(",")
        if separator and advisory_id:
            rows.append((timestamp.strip(), advisory_id.strip()))
    return rows


def ids_changed_since(rows: Sequence[tuple[str, str]], watermark: str | None) -> list[str]:
    """Walk the feed from the newest row and stop at the last timestamp already processed."""
    changed = []
    for timestamp, advisory_id in rows:
        if watermark is not None and timestamp <= watermark:
            break
        changed.append(advisory_id)
    return changed


def read_watermark(path: Path) -> str | None:
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def write_watermark(path: Path, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(timestamp, encoding="utf-8")


def fetch_advisory(advisory_id: str, client: httpx.Client) -> dict:
    response = client.get(f"{ADVISORY_URL}{advisory_id}")
    response.raise_for_status()
    return response.json()


def replace_advisories(existing: Sequence[Advisory], rebuilt: Sequence[Advisory]) -> list[Advisory]:
    """Swap in the rebuilt records, keyed by advisory id and package."""
    by_key = {(a.id, canonicalize_name(a.package)): a for a in existing}
    for advisory in rebuilt:
        by_key[(advisory.id, canonicalize_name(advisory.package))] = advisory
    return list(by_key.values())


def reembed_changed_chunks(
    strategy: str,
    all_chunks: Sequence,
    changed_ids: set[str],
    model,  # noqa: ANN001
    client,  # noqa: ANN001
) -> int:
    """Delete and re-add only the chunks whose advisory changed, leaving the rest untouched."""
    collection = client.get_collection(collection_name(strategy))
    changed = [chunk for chunk in all_chunks if chunk.advisory_id in changed_ids]
    if not changed:
        return 0

    collection.delete(where={"advisory_id": {"$in": sorted(changed_ids)}})
    collection.add(
        ids=[chunk.chunk_id for chunk in changed],
        documents=[chunk.text for chunk in changed],
        embeddings=embed_passages([chunk.text for chunk in changed], model),
        metadatas=[chunk_metadata(chunk) for chunk in changed],
    )
    return len(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-embed only the advisories that changed.")
    parser.add_argument("--max-advisories", type=int, default=200)
    args = parser.parse_args()

    started = time.perf_counter()
    settings = get_settings()
    processed = settings.data_dir / "processed"
    raw = settings.data_dir / "raw"
    report = RefreshReport()

    scope = {
        canonicalize_name(name)
        for name in json.loads((processed / "top_packages.json").read_text(encoding="utf-8"))
    }
    watermark_path = processed / WATERMARK_FILE

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        feed = parse_feed(client.get(MODIFIED_IDS_URL).text)
        report.rows_in_feed = len(feed)
        watermark = read_watermark(watermark_path)
        # A first run follows the full dump, so everything is already current.
        report.seeded = watermark is None
        changed_ids = [] if report.seeded else ids_changed_since(feed, watermark)
        report.changed_since_watermark = len(changed_ids)

        rebuilt: list[Advisory] = []
        for advisory_id in changed_ids[: args.max_advisories]:
            record = fetch_advisory(advisory_id, client)
            in_scope = [
                advisory
                for advisory in advisories_from_osv(record)
                if canonicalize_name(advisory.package) in scope
            ]
            rebuilt.extend(in_scope)

    report.in_scope = len(rebuilt)
    if feed:
        report.new_watermark = feed[0][0]

    if not rebuilt:
        if report.new_watermark:
            write_watermark(watermark_path, report.new_watermark)
        report.seconds = time.perf_counter() - started
        print(report.model_dump_json(indent=2))
        return 0

    nvd = load_nvd_cache(raw / "nvd")
    epss_path = raw / "epss.json"
    epss = json.loads(epss_path.read_text(encoding="utf-8")) if epss_path.exists() else {}
    kev_path = raw / "kev.json"
    known_exploited: set[str] = set()
    if kev_path.exists():
        known_exploited = kev_cve_ids(json.loads(kev_path.read_text(encoding="utf-8")))

    rebuilt = [enrich(advisory, nvd, epss, known_exploited) for advisory in rebuilt]
    report.advisories_rebuilt = len(rebuilt)

    advisories = replace_advisories(read_advisories(processed / "advisories.jsonl"), rebuilt)
    with (processed / "advisories.jsonl").open("w", encoding="utf-8") as handle:
        for advisory in advisories:
            handle.write(advisory.model_dump_json() + "\n")

    tokenizer = default_tokenizer()
    model = load_embedder()
    client = chroma_client()
    changed_advisory_ids = {advisory.id for advisory in rebuilt}

    for strategy, builder in ((FIXED, fixed_size_chunks), (STRUCTURED, structure_aware_chunks)):
        chunks = [chunk for advisory in advisories for chunk in builder(advisory, tokenizer)]
        write_chunks(chunks, processed / CHUNK_FILES[strategy])
        report.chunks_reembedded += reembed_changed_chunks(
            strategy, chunks, changed_advisory_ids, model, client
        )
        # BM25 has no incremental update, but rebuilding it from the chunk file is cheap.
        build_keyword_index(chunks, bm25_path(strategy, processed))

    if report.new_watermark:
        write_watermark(watermark_path, report.new_watermark)

    report.seconds = time.perf_counter() - started
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
