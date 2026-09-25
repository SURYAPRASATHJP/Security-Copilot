from copilot.rag.rerank_results import rerank_results
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs):
        self.pairs = list(pairs)
        return self.scores


def result(chunk_id, text="text", score=0.0):
    return SearchResult(
        chunk=Chunk(
            chunk_id=chunk_id,
            text=text,
            strategy="structured",
            advisory_id=chunk_id,
            package="requests",
            chunk_index=0,
        ),
        score=score,
        source="hybrid",
    )


def test_an_empty_candidate_list_needs_no_model():
    assert rerank_results("anything", []) == []


def test_candidates_are_reordered_by_the_cross_encoder():
    candidates = [result("a"), result("b"), result("c")]
    model = FakeCrossEncoder([0.1, 0.9, 0.5])
    reranked = rerank_results("query", candidates, top_k=3, model=model)
    assert [r.chunk_id for r in reranked] == ["b", "c", "a"]
    assert [round(r.score, 1) for r in reranked] == [0.9, 0.5, 0.1]


def test_only_the_top_few_are_kept():
    candidates = [result(str(n)) for n in range(20)]
    model = FakeCrossEncoder(list(range(20)))
    reranked = rerank_results("query", candidates, top_k=5, model=model)
    assert len(reranked) == 5
    assert [r.chunk_id for r in reranked] == ["19", "18", "17", "16", "15"]


def test_the_query_is_paired_with_every_candidate_text():
    model = FakeCrossEncoder([0.5, 0.4])
    rerank_results("my query", [result("a", "first"), result("b", "second")], model=model)
    assert model.pairs == [("my query", "first"), ("my query", "second")]


def test_reranked_results_say_where_their_score_came_from():
    model = FakeCrossEncoder([0.5])
    assert rerank_results("q", [result("a")], model=model)[0].source == "reranked"
