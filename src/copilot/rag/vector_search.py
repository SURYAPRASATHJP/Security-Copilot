from functools import lru_cache

from copilot.rag.build_search_index import (
    chroma_client,
    collection_name,
    embed_query,
    load_embedder,
)
from copilot.rag.search_result import VECTOR, SearchResult
from copilot.rag.split_into_chunks import STRUCTURED, Chunk

DEFAULT_K = 10


def chunk_from_stored(chunk_id: str, document: str, metadata: dict) -> Chunk:
    """Rebuild a chunk from what the vector store kept, reversing the metadata flattening."""
    cve_ids = metadata.get("cve_ids") or ""
    return Chunk(
        chunk_id=chunk_id,
        text=document,
        strategy=metadata.get("strategy", ""),
        advisory_id=metadata.get("advisory_id", ""),
        package=metadata.get("package", ""),
        chunk_index=int(metadata.get("chunk_index", 0)),
        cve_ids=[cve for cve in cve_ids.split(",") if cve],
        severity=metadata.get("severity"),
        cvss_score=metadata.get("cvss_score"),
        epss_probability=metadata.get("epss_probability"),
        known_exploited=bool(metadata.get("known_exploited", False)),
        published=metadata.get("published"),
    )


@lru_cache
def cached_collection(strategy: str):  # noqa: ANN201
    return chroma_client().get_collection(collection_name(strategy))


def vector_search(
    query: str,
    strategy: str = STRUCTURED,
    k: int = DEFAULT_K,
    package: str | None = None,
    collection=None,  # noqa: ANN001
    model=None,  # noqa: ANN001
) -> list[SearchResult]:
    """Return the chunks closest to the query in embedding space, optionally for one package."""
    collection = collection if collection is not None else cached_collection(strategy)
    model = model if model is not None else load_embedder()

    response = collection.query(
        query_embeddings=[embed_query(query, model)],
        n_results=k,
        where={"package": package} if package else None,
    )

    ids = response["ids"][0]
    documents = response["documents"][0]
    metadatas = response["metadatas"][0]
    distances = response["distances"][0]

    return [
        SearchResult(
            chunk=chunk_from_stored(chunk_id, document, metadata),
            # Chroma reports cosine distance, so a smaller number is a closer match.
            score=1.0 - float(distance),
            source=VECTOR,
        )
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        )
    ]
