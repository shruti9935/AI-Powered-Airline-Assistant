"""Chunker regressions: dropped preamble, colliding ids, oversized chunks."""
from pathlib import Path

from rag.chunking import (MAX_TOKENS, _approx_tokens, chunk_markdown,
                          chunk_pages)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


def test_preamble_is_indexed_even_when_the_doc_has_an_h1():
    """Everything between the H1 and the first H2 used to be discarded.

    In the shipped policy document that is the document id, effective date and
    version — so "which policy version is this?" was unanswerable.
    """
    text = (DOCS_DIR / "airline-rules.md").read_text(encoding="utf-8")
    chunks = chunk_markdown(text, doc_title="airline-rules")
    body = " ".join(c["text"] for c in chunks)
    assert "SWA-POL-2026-01" in body
    assert "Version 3.2" in body


def test_all_sections_are_indexed():
    text = (DOCS_DIR / "airline-rules.md").read_text(encoding="utf-8")
    chunks = chunk_markdown(text, doc_title="airline-rules")
    sections = {c["metadata"]["section"] for c in chunks}
    for expected in ["1. Baggage Allowance", "3. Cancellations & Refunds",
                     "8. Contact & Escalation Departments"]:
        assert expected in sections


def test_chunk_ids_survive_slug_truncation():
    """Two sections sharing a 40-character prefix must not collide — a
    collision makes upsert silently overwrite one with the other."""
    long_prefix = "A" * 45
    doc = (f"# Title\n\n## {long_prefix}First\n\nbody one\n\n"
           f"## {long_prefix}Second\n\nbody two\n")
    chunks = chunk_markdown(doc, doc_title="d")
    ids = [c["id"] for c in chunks]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_oversized_paragraph_is_split():
    """A single paragraph over the budget used to pass through whole, and text
    with no sentence boundaries defeated the sentence splitter."""
    doc = "# T\n\n## S\n\n" + ("word " * 2000)
    chunks = chunk_markdown(doc, doc_title="d")
    assert len(chunks) > 1
    # Allow for the deliberate ~50-word overlap tail on top of the budget.
    assert max(_approx_tokens(c["text"]) for c in chunks) < MAX_TOKENS * 1.5


def test_metadata_carries_source_for_targeted_deletion():
    text = (DOCS_DIR / "airline-rules.md").read_text(encoding="utf-8")
    chunk = chunk_markdown(text, doc_title="airline-rules")[0]
    assert chunk["metadata"]["source"] == "airline-rules"
    assert chunk["metadata"]["language"] == "en"
    assert chunk["metadata"]["doc_title"]


def test_pdf_style_pages_do_not_collapse_into_one_chunk():
    """PDF text has no '##' headings, so the markdown path produced a single
    giant chunk for the whole file."""
    pages = ["First page about baggage.", "Second page about refunds."]
    chunks = chunk_pages(pages, source="policy-pdf")
    assert len(chunks) == 2
    assert {c["metadata"]["section"] for c in chunks} == {"Page 1", "Page 2"}
