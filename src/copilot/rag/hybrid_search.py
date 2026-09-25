from collections.abc import Sequence

from copilot.rag.keyword_search import keyword_search
from copilot.rag.search_result import HYBRID, SearchResult
from copilot.rag.split_into_chunks import STRUCTURED
from copilot.rag.vector_search import vector_search

# The constant from the original reciprocal rank fusion paper, which damps the top ranks.
RRF_K = 60
DEFAULT_K = 10
CANDIDATES_PER_SOURCE = 20


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[SearchResult]], k: int = RRF_K
) -> list[tuple[str, float]]:
    """Merge ranked lists by summing 1/(k + rank), ignoring the original scores."""
    fused: dict[str, float] = {}
    for results in ranked_lists:
        for rank, result in enumerate(results, start=1):
            fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: -pair[1])


def hybrid_search(
    query: str,
    strategy: str = STRUCTURED,
    k: int = DEFAULT_K,
    package: str | None = None,
    candidates: int = CANDIDATES_PER_SOURCE,
    keyword_results: Sequence[SearchResult] | None = None,
    vector_results: Sequence[SearchResult] | None = None,
) -> list[SearchResult]:
    """Merge keyword and vector results so exact ids and plain meaning both find their chunk."""
    keywords = (
        keyword_results
        if keyword_results is not None
        else keyword_search(query, strategy, candidates)
    )
    vectors = (
        vector_results
        if vector_results is not None
        else vector_search(query, strategy, candidates, package)
    )

    by_id = {result.chunk_id: result for result in [*vectors, *keywords]}
    fused = reciprocal_rank_fusion([keywords, vectors])

    return [
        by_id[chunk_id].model_copy(update={"score": score, "source": HYBRID})
        for chunk_id, score in fused[:k]
        if chunk_id in by_id
    ]
