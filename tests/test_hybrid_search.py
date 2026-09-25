from copilot.rag.hybrid_search import RRF_K, hybrid_search, reciprocal_rank_fusion
from copilot.rag.search_result import SearchResult
from copilot.rag.split_into_chunks import Chunk


def result(chunk_id, score=1.0, source="keyword", package="requests", text="text"):
    return SearchResult(
        chunk=Chunk(
            chunk_id=chunk_id,
            text=text,
            strategy="structured",
            advisory_id=chunk_id.split("|")[0],
            package=package,
            chunk_index=0,
        ),
        score=score,
        source=source,
    )


def test_a_chunk_ranked_first_by_both_sources_wins():
    keywords = [result("GHSA-a|x", source="keyword"), result("GHSA-b|x")]
    vectors = [result("GHSA-a|x", source="vector"), result("GHSA-c|x", source="vector")]
    fused = reciprocal_rank_fusion([keywords, vectors])
    assert fused[0][0] == "GHSA-a|x"
    assert fused[0][1] == 2 / (RRF_K + 1)


def test_fusion_ignores_the_original_scores():
    keywords = [result("GHSA-a|x", score=999.0)]
    vectors = [result("GHSA-b|x", score=0.001, source="vector")]
    fused = dict(reciprocal_rank_fusion([keywords, vectors]))
    assert fused["GHSA-a|x"] == fused["GHSA-b|x"]


def test_a_lower_rank_contributes_less():
    first = reciprocal_rank_fusion([[result("a|x"), result("b|x")]])
    assert first[0][1] > first[1][1]


def test_an_exact_identifier_query_keeps_the_keyword_hit():
    keywords = [result("GHSA-j8r2|requests")]
    vectors = [result("GHSA-other|flask", source="vector")]
    merged = hybrid_search("CVE-2023-32681", keyword_results=keywords, vector_results=vectors)
    assert merged[0].chunk_id == "GHSA-j8r2|requests"
    assert merged[0].source == "hybrid"


def test_a_meaning_query_keeps_the_vector_hit():
    keywords = []
    vectors = [result("GHSA-meaning|requests", source="vector")]
    merged = hybrid_search(
        "proxy credentials leak to the wrong host",
        keyword_results=keywords,
        vector_results=vectors,
    )
    assert [r.chunk_id for r in merged] == ["GHSA-meaning|requests"]


def test_a_chunk_found_by_both_sources_appears_once():
    shared = result("GHSA-a|x")
    merged = hybrid_search(
        "anything",
        keyword_results=[shared],
        vector_results=[result("GHSA-a|x", source="vector")],
    )
    assert len(merged) == 1


def test_the_result_count_is_respected():
    keywords = [result(f"GHSA-{n}|x") for n in range(10)]
    merged = hybrid_search("anything", k=3, keyword_results=keywords, vector_results=[])
    assert len(merged) == 3


def test_two_empty_sources_give_no_results():
    assert hybrid_search("anything", keyword_results=[], vector_results=[]) == []
