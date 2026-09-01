"""Hierarchical, structure-aware chunking.

Split a document along its heading structure first (H2 sections), then split
long sections into ~300-500-token paragraph chunks with ~50-token overlap.
Every chunk carries metadata: source, doc_title, section, language.
"""
import hashlib
import re
from typing import Dict, List

MAX_TOKENS = 400          # target chunk size (approx. tokens)
OVERLAP_TOKENS = 50
PREAMBLE_SECTION = "Overview"


def _approx_tokens(text: str) -> int:
    # Rough heuristic: 1 token is about 0.75 words for English-like text.
    return int(len(text.split()) / 0.75)


# Word budget matching MAX_TOKENS, used as the last-resort split.
MAX_WORDS = int(MAX_TOKENS * 0.75)


def _split_words(text: str) -> List[str]:
    """Hard split on a word window — the fallback when a run of text contains
    no sentence boundaries at all (tables, transcripts, minified prose)."""
    words = text.split()
    return [" ".join(words[i:i + MAX_WORDS]) for i in range(0, len(words), MAX_WORDS)]


def _split_paragraph(para: str) -> List[str]:
    """Split one oversized paragraph on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?。।])\s+", para)
    pieces, current = [], ""
    for sentence in sentences:
        candidate = (current + " " + sentence).strip()
        if current and _approx_tokens(candidate) > MAX_TOKENS:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    # A single sentence can still blow the budget — split those on words so no
    # chunk is ever returned above MAX_TOKENS.
    final = []
    for piece in pieces:
        final.extend(_split_words(piece) if _approx_tokens(piece) > MAX_TOKENS else [piece])
    return final


def _split_long_section(text: str) -> List[str]:
    """Split a section into paragraph groups of <= MAX_TOKENS with overlap."""
    paragraphs = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # A single paragraph can exceed the budget on its own; break it up
        # rather than emitting one oversized chunk.
        paragraphs.extend(_split_paragraph(para) if _approx_tokens(para) > MAX_TOKENS
                          else [para])

    chunks, current = [], ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip()
        if current and _approx_tokens(candidate) > MAX_TOKENS:
            chunks.append(current)
            # start next chunk with an overlap tail from the previous one
            tail_words = current.split()[-OVERLAP_TOKENS:]
            current = " ".join(tail_words) + "\n\n" + para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _chunk_id(source: str, section: str, section_index: int, piece_index: int) -> str:
    """Stable, collision-free chunk id.

    The section slug is truncated for readability, so a short hash of the full
    section name plus its ordinal is appended — two sections sharing a 40-char
    prefix would otherwise produce the same id and silently overwrite each
    other on upsert.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")[:40] or "section"
    digest = hashlib.sha1(f"{section_index}:{section}".encode()).hexdigest()[:6]
    return f"{source}#{slug}-{digest}#p{piece_index}"


def chunk_text(text: str, source: str, language: str = "en",
               sections: List[tuple] = None, doc_title: str = None) -> List[Dict]:
    """Turn pre-split (section, body) pairs into embeddable chunks."""
    title = doc_title or source
    chunks = []
    for section_index, (section, body) in enumerate(sections or []):
        body = (body or "").strip()
        if not body:
            continue
        pieces = (_split_long_section(body) if _approx_tokens(body) > MAX_TOKENS
                  else [body])
        for piece_index, piece in enumerate(pieces):
            chunks.append({
                "id": _chunk_id(source, section, section_index, piece_index),
                # Prepend the section heading so the embedding carries structure
                "text": f"{section}\n{piece}",
                "metadata": {"source": source, "doc_title": title,
                             "section": section, "language": language},
            })
    return chunks


def split_markdown_sections(text: str) -> tuple:
    """Return (doc_title, [(section, body), ...]) split on H2 headings."""
    h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = h1.group(1).strip() if h1 else None

    # parts = [preamble, heading1, body1, heading2, body2, ...]
    parts = re.split(r"^##\s+(.+)$", text, flags=re.MULTILINE)

    # The preamble is everything before the first H2. It is kept even when the
    # document has an H1 — it carries document ids, versions and effective
    # dates that are otherwise never indexed.
    preamble = re.sub(r"^#\s+.+$", "", parts[0], count=1, flags=re.MULTILINE).strip()
    sections = []
    if preamble:
        sections.append((title or PREAMBLE_SECTION, preamble))
    for i in range(1, len(parts) - 1, 2):
        sections.append((parts[i].strip(), parts[i + 1].strip()))
    return title, sections


def chunk_markdown(text: str, doc_title: str, language: str = "en") -> List[Dict]:
    """Return [{id, text, metadata}] chunks from a markdown document.

    ``doc_title`` is the source name (usually the filename stem); the document's
    own H1, when present, becomes the ``doc_title`` metadata value.
    """
    title, sections = split_markdown_sections(text)
    return chunk_text(text, source=doc_title, language=language,
                      sections=sections, doc_title=title or doc_title)


def chunk_pages(pages: List[str], source: str, language: str = "en",
                doc_title: str = None) -> List[Dict]:
    """Chunk extracted PDF/plain-text pages. Uses markdown structure when the
    text happens to have it, and falls back to one section per page."""
    joined = "\n\n".join(pages)
    if re.search(r"^##\s+.+$", joined, re.MULTILINE):
        return chunk_markdown(joined, doc_title=source, language=language)
    sections = [(f"Page {n}", page.strip())
                for n, page in enumerate(pages, start=1) if page.strip()]
    return chunk_text(joined, source=source, language=language,
                      sections=sections, doc_title=doc_title or source)
