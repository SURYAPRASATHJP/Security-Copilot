import argparse
import pickle
import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from copilot.rag.split_into_chunks import FIXED, STRUCTURED, Chunk, read_chunks
from copilot.settings import get_settings

# The bge models want this exact instruction on a query and nothing on a passage.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

CHROMA_BATCH = 1000
EMBED_BATCH = 64

IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._\-]*")

CHUNK_FILES = {FIXED: "chunks_fixed.jsonl", STRUCTURED: "chunks_structured.jsonl"}


def tokenize_for_bm25(text: str) -> list[str]:
    """Split text so an exact identifier such as CVE-2023-32681 survives as a single token."""
    return IDENTIFIER.findall(text.lower())


def collection_name(strategy: str) -> str:
    return f"advisories_{strategy}"


def bm25_path(strategy: str, folder: Path) -> Path:
    return folder / f"bm25_{strategy}.pkl"


def chunk_metadata(chunk: Chunk) -> dict[str, str | float | bool | int]:
    """Flatten a chunk's metadata into the scalar types Chroma accepts."""
    metadata: dict[str, str | float | bool | int] = {
        "advisory_id": chunk.advisory_id,
        "package": chunk.package,
        "strategy": chunk.strategy,
        "chunk_index": chunk.chunk_index,
        "cve_ids": ",".join(chunk.cve_ids),
        "known_exploited": chunk.known_exploited,
    }
    if chunk.severity:
        metadata["severity"] = chunk.severity
    if chunk.cvss_score is not None:
        metadata["cvss_score"] = chunk.cvss_score
    if chunk.epss_probability is not None:
        metadata["epss_probability"] = chunk.epss_probability
    if chunk.published:
        metadata["published"] = chunk.published
    return metadata


@lru_cache
def load_embedder(model_name: str | None = None):  # noqa: ANN201
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name or get_settings().embedding_model_name)


def embed_passages(texts: Sequence[str], model) -> list[list[float]]:  # noqa: ANN001
    vectors = model.encode(
        list(texts), batch_size=EMBED_BATCH, normalize_embeddings=True, show_progress_bar=False
    )
    return [vector.tolist() for vector in vectors]


def embed_query(text: str, model) -> list[float]:  # noqa: ANN001
    vector = model.encode(QUERY_PREFIX + text, normalize_embeddings=True, show_progress_bar=False)
    return vector.tolist()


@lru_cache
def chroma_client():  # noqa: ANN201
    import chromadb

    settings = get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def build_vector_index(chunks: Sequence[Chunk], strategy: str, model, client) -> int:  # noqa: ANN001
    name = collection_name(strategy)
    if name in {existing.name for existing in client.list_collections()}:
        client.delete_collection(name)
    collection = client.create_collection(name, metadata={"hnsw:space": "cosine"})

    for start in range(0, len(chunks), CHROMA_BATCH):
        batch = chunks[start : start + CHROMA_BATCH]
        collection.add(
            ids=[chunk.chunk_id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            embeddings=embed_passages([chunk.text for chunk in batch], model),
            metadatas=[chunk_metadata(chunk) for chunk in batch],
        )
    return collection.count()


def build_keyword_index(chunks: Sequence[Chunk], path: Path) -> int:
    from rank_bm25 import BM25Okapi

    tokenized = [tokenize_for_bm25(chunk.text) for chunk in chunks]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(
            {"chunk_ids": [chunk.chunk_id for chunk in chunks], "bm25": BM25Okapi(tokenized)},
            handle,
        )
    return len(chunks)


def load_keyword_index(path: Path) -> dict:
    with path.open("rb") as handle:
        return pickle.load(handle)


def load_chunks_by_id(strategy: str) -> dict[str, Chunk]:
    processed = get_settings().data_dir / "processed"
    chunks = read_chunks(processed / CHUNK_FILES[strategy])
    return {chunk.chunk_id: chunk for chunk in chunks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the vector and keyword indexes.")
    parser.add_argument("--strategy", choices=[FIXED, STRUCTURED, "both"], default="both")
    args = parser.parse_args()

    settings = get_settings()
    processed = settings.data_dir / "processed"
    model = load_embedder()
    client = chroma_client()

    strategies = [FIXED, STRUCTURED] if args.strategy == "both" else [args.strategy]
    for strategy in strategies:
        chunks = read_chunks(processed / CHUNK_FILES[strategy])
        vectors = build_vector_index(chunks, strategy, model, client)
        keywords = build_keyword_index(chunks, bm25_path(strategy, processed))
        print(
            f"{strategy}: {vectors} vectors in {collection_name(strategy)}, "
            f"{keywords} bm25 documents"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
