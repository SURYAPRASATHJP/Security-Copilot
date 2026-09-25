from datetime import datetime

from copilot.data_collection.advisory import Advisory, VersionRange
from copilot.rag.split_into_chunks import (
    affected_range,
    context_header,
    fixed_size_chunks,
    pack_paragraphs,
    paragraphs,
    read_chunks,
    structure_aware_chunks,
    summary_card,
    token_windows,
    write_chunks,
)


class WordTokenizer:
    """Stands in for the embedding tokenizer so the tests stay offline and fast."""

    def __init__(self):
        self.vocab = []

    def encode(self, text):
        ids = []
        for word in text.split():
            if word not in self.vocab:
                self.vocab.append(word)
            ids.append(self.vocab.index(word))
        return ids

    def decode(self, tokens):
        return " ".join(self.vocab[token] for token in tokens)


ADVISORY = Advisory(
    id="GHSA-j8r2-6x86-q33q",
    package="requests",
    aliases=["CVE-2023-32681"],
    ranges=[VersionRange(introduced="2.3.0", fixed="2.31.0")],
    fixed_versions=["2.31.0"],
    summary="Unintended leak of Proxy-Authorization header",
    details="First paragraph about the leak.\n\nSecond paragraph about the fix.",
    severity="MODERATE",
    cvss_score=6.1,
    epss_probability=0.0297,
    known_exploited=False,
    published=datetime(2023, 5, 26, 18, 30),
)


def test_affected_range_reads_as_a_version_specifier():
    assert affected_range(ADVISORY) == ">=2.3.0,<2.31.0"


def test_affected_range_handles_last_affected_and_open_ranges():
    last = Advisory(id="a", package="p", ranges=[VersionRange(introduced="0", last_affected="5.3")])
    open_ended = Advisory(id="a", package="p", ranges=[VersionRange(introduced="1.0")])
    assert affected_range(last) == ">=0,<=5.3"
    assert affected_range(open_ended) == ">=1.0"
    assert affected_range(Advisory(id="a", package="p")) == "not stated"


def test_the_context_header_names_the_advisory_and_the_package():
    assert context_header(ADVISORY) == "Advisory GHSA-j8r2-6x86-q33q for package requests:"


def test_the_summary_card_is_self_contained():
    card = summary_card(ADVISORY)
    assert "Advisory GHSA-j8r2-6x86-q33q for package requests:" in card
    assert "Fixed in: 2.31.0" in card
    assert ">=2.3.0,<2.31.0" in card
    assert "CVSS 6.1" in card
    assert "0.02970" in card
    assert "Known exploited: no" in card
    assert "CVE-2023-32681" in card


def test_the_summary_card_says_so_when_there_is_no_fix():
    card = summary_card(Advisory(id="GHSA-x", package="p", known_exploited=True))
    assert "Fixed in: no fix listed" in card
    assert "Severity: unrated" in card
    assert "EPSS): not scored" in card
    assert "Known exploited: yes" in card


def test_short_text_is_one_window():
    assert token_windows("a b c", WordTokenizer(), window=10) == ["a b c"]


def test_empty_text_produces_no_windows():
    assert token_windows("   ", WordTokenizer()) == []


def test_long_text_is_split_with_overlap():
    text = " ".join(f"w{n}" for n in range(25))
    windows = token_windows(text, WordTokenizer(), window=10, overlap=2)
    assert len(windows) == 3
    assert windows[0].split()[0] == "w0"
    # The last two tokens of a window open the next one.
    assert windows[1].split()[0] == "w8"


def test_the_final_window_is_not_repeated():
    text = " ".join(f"w{n}" for n in range(20))
    windows = token_windows(text, WordTokenizer(), window=10, overlap=2)
    assert windows[-1].split()[-1] == "w19"
    assert len(windows) == len(set(windows))


def test_paragraphs_split_on_blank_lines_and_are_stripped():
    assert paragraphs("  one  \n\n\n two \n\n") == ["one", "two"]


def test_paragraphs_are_packed_up_to_the_window():
    blocks = ["a b c", "d e f", "g h i"]
    packed = pack_paragraphs(blocks, WordTokenizer(), window=6)
    assert packed == ["a b c\n\nd e f", "g h i"]


def test_an_oversized_paragraph_is_split_on_its_own():
    blocks = ["a b", " ".join(f"w{n}" for n in range(20))]
    packed = pack_paragraphs(blocks, WordTokenizer(), window=5)
    assert packed[0] == "a b"
    assert len(packed) > 2
    assert all(len(piece.split()) <= 5 for piece in packed)


def test_the_fixed_strategy_names_the_advisory_only_in_its_first_chunk():
    chunks = fixed_size_chunks(ADVISORY, WordTokenizer(), window=8, overlap=2)
    assert "GHSA-j8r2-6x86-q33q" in chunks[0].text
    assert not any("GHSA-j8r2-6x86-q33q" in chunk.text for chunk in chunks[1:])


def test_the_structured_strategy_puts_the_header_on_every_chunk():
    chunks = structure_aware_chunks(ADVISORY, WordTokenizer(), window=50)
    assert len(chunks) >= 2
    assert all(chunk.text.startswith(context_header(ADVISORY)) for chunk in chunks)


def test_the_first_structured_chunk_is_the_summary_card():
    chunks = structure_aware_chunks(ADVISORY, WordTokenizer(), window=50)
    assert chunks[0].text == summary_card(ADVISORY)


def test_chunk_ids_are_unique_and_carry_the_strategy():
    chunks = fixed_size_chunks(ADVISORY, WordTokenizer(), window=8, overlap=2)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all("|fixed|" in chunk.chunk_id for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_every_chunk_keeps_the_filtering_metadata():
    chunk = structure_aware_chunks(ADVISORY, WordTokenizer())[0]
    assert chunk.package == "requests"
    assert chunk.cve_ids == ["CVE-2023-32681"]
    assert chunk.severity == "MODERATE"
    assert chunk.epss_probability == 0.0297
    assert chunk.published == "2023-05-26"


def test_an_advisory_with_no_details_still_produces_a_card():
    bare = Advisory(id="GHSA-x", package="p", summary="Short one")
    chunks = structure_aware_chunks(bare, WordTokenizer())
    assert len(chunks) == 1


def test_chunks_round_trip_through_disk(tmp_path):
    chunks = structure_aware_chunks(ADVISORY, WordTokenizer())
    path = tmp_path / "chunks.jsonl"
    assert write_chunks(chunks, path) == len(chunks)
    assert [c.chunk_id for c in read_chunks(path)] == [c.chunk_id for c in chunks]


def test_writing_a_repeated_chunk_id_is_refused(tmp_path):
    import pytest

    chunk = structure_aware_chunks(ADVISORY, WordTokenizer())[0]
    with pytest.raises(ValueError, match="repeated chunk ids"):
        write_chunks([chunk, chunk], tmp_path / "chunks.jsonl")
