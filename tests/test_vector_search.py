import numpy as np

from copilot.rag.vector_search import chunk_from_stored, vector_search

STORED_METADATA = {
    "advisory_id": "GHSA-a",
    "package": "requests",
    "strategy": "structured",
    "chunk_index": 2,
    "cve_ids": "CVE-2023-32681,CVE-2024-1",
    "known_exploited": True,
    "severity": "MODERATE",
    "cvss_score": 6.1,
    "epss_probability": 0.0297,
    "published": "2023-05-26",
}


class FakeCollection:
    def __init__(self, response):
        self.response = response
        self.last_query = None

    def query(self, **kwargs):
        self.last_query = kwargs
        return self.response


class FakeEmbedder:
    def encode(self, text, **kwargs):
        return np.zeros(4)


def response_with(ids, distances):
    return {
        "ids": [ids],
        "documents": [[f"text for {i}" for i in ids]],
        "metadatas": [[STORED_METADATA for _ in ids]],
        "distances": [distances],
    }


def test_stored_metadata_is_turned_back_into_a_chunk():
    chunk = chunk_from_stored("GHSA-a|requests|structured|2", "the text", STORED_METADATA)
    assert chunk.cve_ids == ["CVE-2023-32681", "CVE-2024-1"]
    assert chunk.known_exploited is True
    assert chunk.chunk_index == 2
    assert chunk.cvss_score == 6.1


def test_missing_optional_metadata_comes_back_as_none():
    chunk = chunk_from_stored("id", "text", {"advisory_id": "GHSA-b", "package": "p"})
    assert chunk.cve_ids == []
    assert chunk.cvss_score is None
    assert chunk.severity is None
    assert chunk.known_exploited is False


def test_a_closer_distance_becomes_a_higher_score():
    collection = FakeCollection(response_with(["a", "b"], [0.1, 0.4]))
    results = vector_search(
        "leaking proxy credentials", collection=collection, model=FakeEmbedder()
    )
    assert [round(r.score, 2) for r in results] == [0.9, 0.6]
    assert all(r.source == "vector" for r in results)


def test_a_package_filter_is_passed_to_the_store():
    collection = FakeCollection(response_with(["a"], [0.2]))
    vector_search("anything", package="requests", collection=collection, model=FakeEmbedder())
    assert collection.last_query["where"] == {"package": "requests"}


def test_no_package_means_no_filter():
    collection = FakeCollection(response_with(["a"], [0.2]))
    vector_search("anything", collection=collection, model=FakeEmbedder())
    assert collection.last_query["where"] is None


def test_the_requested_result_count_is_passed_through():
    collection = FakeCollection(response_with(["a"], [0.2]))
    vector_search("anything", k=7, collection=collection, model=FakeEmbedder())
    assert collection.last_query["n_results"] == 7
