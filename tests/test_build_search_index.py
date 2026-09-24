import pickle

from copilot.rag.build_search_index import (
    QUERY_PREFIX,
    bm25_path,
    build_keyword_index,
    chunk_metadata,
    collection_name,
    load_keyword_index,
    tokenize_for_bm25,
)
from copilot.rag.split_into_chunks import Chunk

CHUNK = Chunk(
    chunk_id="GHSA-a|requests|structured|0",
    text="Advisory GHSA-a for package requests: fixed in 2.31.0",
    strategy="structured",
    advisory_id="GHSA-a",
    package="requests",
    chunk_index=0,
    cve_ids=["CVE-2023-32681", "CVE-2024-1"],
    severity="MODERATE",
    cvss_score=6.1,
    epss_probability=0.0297,
    known_exploited=True,
    published="2023-05-26",
)


def test_an_advisory_id_survives_tokenization_whole():
    assert "cve-2023-32681" in tokenize_for_bm25("Is CVE-2023-32681 relevant?")
    assert "ghsa-j8r2-6x86-q33q" in tokenize_for_bm25("See GHSA-j8r2-6x86-q33q for details.")


def test_a_version_number_survives_tokenization_whole():
    assert "2.31.0" in tokenize_for_bm25("Upgrade to 2.31.0 now.")


def test_punctuation_is_dropped_and_case_is_folded():
    assert tokenize_for_bm25("Requests, (urllib3)!") == ["requests", "urllib3"]


def test_metadata_is_flattened_to_scalars():
    metadata = chunk_metadata(CHUNK)
    assert metadata["cve_ids"] == "CVE-2023-32681,CVE-2024-1"
    assert metadata["known_exploited"] is True
    assert metadata["cvss_score"] == 6.1
    assert all(isinstance(value, str | int | float | bool) for value in metadata.values())


def test_absent_metadata_is_left_out_rather_than_set_to_none():
    bare = Chunk(
        chunk_id="GHSA-b|p|fixed|0",
        text="text",
        strategy="fixed",
        advisory_id="GHSA-b",
        package="p",
        chunk_index=0,
    )
    metadata = chunk_metadata(bare)
    assert "cvss_score" not in metadata
    assert "severity" not in metadata
    assert "published" not in metadata
    assert metadata["cve_ids"] == ""


def test_collection_and_index_names_are_separate_per_strategy(tmp_path):
    assert collection_name("fixed") != collection_name("structured")
    assert bm25_path("fixed", tmp_path) != bm25_path("structured", tmp_path)
    assert bm25_path("fixed", tmp_path).name == "bm25_fixed.pkl"


def test_the_keyword_index_stores_chunk_ids_alongside_the_model(tmp_path):
    path = bm25_path("structured", tmp_path)
    assert build_keyword_index([CHUNK], path) == 1
    saved = load_keyword_index(path)
    assert saved["chunk_ids"] == [CHUNK.chunk_id]
    assert saved["bm25"].get_scores(tokenize_for_bm25("requests")) is not None


def test_the_keyword_index_is_a_readable_pickle(tmp_path):
    path = bm25_path("fixed", tmp_path)
    build_keyword_index([CHUNK], path)
    with path.open("rb") as handle:
        assert set(pickle.load(handle)) == {"chunk_ids", "bm25"}


def test_the_query_prefix_is_the_one_bge_expects():
    assert QUERY_PREFIX == "Represent this sentence for searching relevant passages: "
