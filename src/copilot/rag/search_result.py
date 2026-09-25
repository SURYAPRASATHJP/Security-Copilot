from pydantic import BaseModel

from copilot.rag.split_into_chunks import Chunk

KEYWORD = "keyword"
VECTOR = "vector"
HYBRID = "hybrid"
RERANKED = "reranked"


class SearchResult(BaseModel):
    chunk: Chunk
    score: float
    source: str

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def advisory_id(self) -> str:
        return self.chunk.advisory_id

    @property
    def package(self) -> str:
        return self.chunk.package

    @property
    def identifiers(self) -> list[str]:
        """Return every id this result could be cited by."""
        return [self.chunk.advisory_id, *self.chunk.cve_ids]
