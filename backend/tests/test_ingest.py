"""Ingest ordering and near-duplicate handling."""
from pathlib import Path

from rag import ingest

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


def test_structured_sources_are_read_before_flattened_ones():
    """The shipped policies exist as both Markdown and PDF.

    Ordering by filename alone would hand the decision to an accident of
    alphabetics ('airline-rules-and-regulations.pdf' sorts before
    'airline-rules.md'), and the flattened PDF would win over the
    heading-aware Markdown the README calls the canonical source.
    """
    names = [source for source, _ in ingest.load_documents()]
    assert names.index("airline-rules") < names.index("airline-rules-and-regulations")


def test_shipped_pdf_twin_is_recognised_as_a_duplicate():
    documents = dict(ingest.load_documents())
    markdown = ingest._tokens(
        " ".join(c["text"] for c in documents["airline-rules"]))
    pdf = ingest._tokens(
        " ".join(c["text"] for c in documents["airline-rules-and-regulations"]))
    assert ingest.coverage(pdf, markdown) >= ingest.DUPLICATE_COVERAGE


def test_a_genuinely_new_document_is_not_treated_as_a_duplicate():
    """The guard must not swallow new material that merely shares jargon."""
    documents = dict(ingest.load_documents())
    indexed = ingest._tokens(
        " ".join(c["text"] for c in documents["airline-rules"]))
    new_doc = ingest._tokens(
        "SkyWings loyalty programme. Silver members earn 3 miles per rupee spent "
        "and receive complimentary lounge access at 14 domestic airports. Gold "
        "members earn 5 miles and may nominate two companions annually. Miles "
        "expire 36 months after accrual unless the account records qualifying "
        "activity. Redemption starts at 8000 miles for a domestic one-way award.")
    assert ingest.coverage(new_doc, indexed) < ingest.DUPLICATE_COVERAGE


def test_every_supported_extension_is_loaded():
    assert {".md", ".markdown", ".txt", ".pdf"} == set(ingest.SUPPORTED_SUFFIXES)
    assert set(ingest.SUFFIX_PRIORITY) == set(ingest.SUPPORTED_SUFFIXES)


def test_pdf_is_chunked_per_page_not_as_one_blob():
    documents = dict(ingest.load_documents())
    pdf_chunks = documents["airline-rules-and-regulations"]
    assert len(pdf_chunks) > 1
    assert all(c["metadata"]["source"] == "airline-rules-and-regulations"
               for c in pdf_chunks)
