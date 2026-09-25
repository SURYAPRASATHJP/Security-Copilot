from collections.abc import Sequence
from functools import lru_cache

from copilot.rag.search_result import RERANKED, SearchResult
from copilot.settings import get_settings

DEFAULT_TOP_K = 5


@lru_cache
def load_reranker(model_name: str | None = None):  # noqa: ANN201
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name or get_settings().reranker_model_name)


def rerank_results(
    query: str,
    results: Sequence[SearchResult],
    top_k: int = DEFAULT_TOP_K,
    model=None,  # noqa: ANN001
) -> list[SearchResult]:
    """Score every candidate against the query as a pair, then keep the best few."""
    if not results:
        return []

    model = model if model is not None else load_reranker()
    scores = model.predict([(query, result.chunk.text) for result in results])

    scored = [
        result.model_copy(update={"score": float(score), "source": RERANKED})
        for result, score in zip(results, scores, strict=True)
    ]
    return sorted(scored, key=lambda result: -result.score)[:top_k]
