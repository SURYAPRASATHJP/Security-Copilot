from functools import lru_cache

from copilot.rag.build_search_index import (
    bm25_path,
    load_chunks_by_id,
    load_keyword_index,
    tokenize_for_bm25,
)
from copilot.rag.search_result import KEYWORD, SearchResult
from copilot.rag.split_into_chunks import STRUCTURED, Chunk
from copilot.settings import get_settings

DEFAULT_K = 10


@lru_cache
def cached_keyword_index(strategy: str) -> dict:
    processed = get_settings().data_dir / "processed"
    return load_keyword_index(bm25_path(strategy, processed))


@lru_cache
def cached_chunks(strategy: str) -> dict[str, Chunk]:
    return load_chunks_by_id(strategy)


def keyword_search(
    query: str,
    strategy: str = STRUCTURED,
    k: int = DEFAULT_K,
    index: dict | None = None,
    chunks_by_id: dict[str, Chunk] | None = None,
) -> list[SearchResult]:
    """Return the chunks whose words best match the query, highest BM25 score first."""
    index = index if index is not None else cached_keyword_index(strategy)
    chunks_by_id = chunks_by_id if chunks_by_id is not None else cached_chunks(strategy)

    scores = index["bm25"].get_scores(tokenize_for_bm25(query))
    ranked = sorted(zip(index["chunk_ids"], scores, strict=True), key=lambda pair: -pair[1])

    results = []
    for chunk_id, score in ranked[:k]:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None or score <= 0:
            continue
        results.append(SearchResult(chunk=chunk, score=float(score), source=KEYWORD))
    return results
