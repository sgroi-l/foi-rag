import pytest
from src.ingestion.chunker import chunk_pages, split_sentences, count_tokens, MAX_TOKENS


# --- split_sentences ---

def test_split_sentences_basic():
    result = split_sentences("Hello world. Goodbye world.")
    assert result == ["Hello world.", "Goodbye world."]

def test_split_sentences_exclamation_and_question():
    result = split_sentences("Really? Yes! Absolutely.")
    assert result == ["Really?", "Yes!", "Absolutely."]

def test_split_sentences_empty():
    assert split_sentences("") == []

def test_split_sentences_no_punctuation():
    # No sentence-ending punctuation — treated as one sentence
    result = split_sentences("no punctuation here")
    assert result == ["no punctuation here"]


# --- count_tokens ---

def test_count_tokens_nonempty():
    # Just verify it returns a positive integer for real text
    assert count_tokens("Camden Council FOI request") > 0

def test_count_tokens_empty():
    assert count_tokens("") == 0

def test_count_tokens_longer_is_more():
    short = count_tokens("hello")
    long = count_tokens("hello " * 100)
    assert long > short


# --- chunk_pages ---

def test_chunk_pages_empty():
    assert chunk_pages([]) == []

def test_chunk_pages_blank_page_skipped():
    result = chunk_pages([(1, "   \n  ")])
    assert result == []

def test_chunk_pages_short_page_single_chunk():
    pages = [(1, "This is a short page.")]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == "This is a short page."

def test_chunk_pages_preserves_page_number():
    pages = [(7, "Page seven content.")]
    chunks = chunk_pages(pages)
    assert chunks[0].page_number == 7

def test_chunk_pages_token_count_matches_content():
    pages = [(1, "Some text on a page.")]
    chunks = chunk_pages(pages)
    assert chunks[0].token_count == count_tokens(chunks[0].content)

def test_chunk_pages_long_page_splits():
    # Build a page that exceeds MAX_TOKENS
    # sentence * 60 is only ~721 tokens (under 800), so use 100 to reliably exceed it
    sentence = "Camden Council received a freedom of information request about housing policy. "
    long_text = sentence * 100
    pages = [(1, long_text)]
    chunks = chunk_pages(pages)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= MAX_TOKENS + count_tokens(sentence)  # allow one sentence overhang

def test_chunk_pages_long_page_overlap():
    # The last sentence of chunk N should appear as the first sentence of chunk N+1
    sentence = "Camden Council received a freedom of information request about housing policy. "
    long_text = sentence * 100
    pages = [(1, long_text)]
    chunks = chunk_pages(pages)
    assert len(chunks) >= 2
    last_sentence_of_first = chunks[0].content.split(". ")[-1].strip(" .")
    first_sentence_of_second = chunks[1].content.split(". ")[0].strip(" .")
    assert last_sentence_of_first == first_sentence_of_second

def test_chunk_pages_multiple_pages():
    pages = [(1, "First page content."), (2, "Second page content.")]
    chunks = chunk_pages(pages)
    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2

def test_chunk_pages_collapses_excessive_newlines():
    pages = [(1, "Before.\n\n\n\n\nAfter.")]
    chunks = chunk_pages(pages)
    assert "\n\n\n" not in chunks[0].content

def test_chunk_pages_long_page_chunk_index_increments():
    sentence = "Camden Council received a freedom of information request about housing policy. "
    long_text = sentence * 100
    pages = [(1, long_text)]
    chunks = chunk_pages(pages)
    # Long pages start chunk_index at 1 (0 is reserved for single-chunk pages)
    assert chunks[0].chunk_index == 1
    assert chunks[1].chunk_index == 2
