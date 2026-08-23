"""Hierarchical, structure-aware chunking.

Split a document along its heading structure first (H2 sections), then split
long sections into ~300-500-token paragraph chunks with ~50-token overlap.
Every chunk carries metadata: doc_title, section, language.
"""
import re
from typing import Dict, List

MAX_TOKENS = 400          # target chunk size (approx. tokens)
OVERLAP_TOKENS = 50


def _approx_tokens(text: str) -> int:
    # Rough heuristic: 1 token is about 0.75 words for English-like text.
    return int(len(text.split()) / 0.75)


def _split_long_section(text: str) -> List[str]:
    """Split a section into paragraph groups of <= MAX_TOKENS with overlap."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
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


def chunk_markdown(text: str, doc_title: str, language: str = "en") -> List[Dict]:
    """Return [{id, text, metadata}] chunks from a markdown document."""
    h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = h1.group(1).strip() if h1 else doc_title

    # Split on H2 headings — the structure-aware step.
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    parts = re.split(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    sections = []
    if parts[0].strip() and not h1:
        sections.append(("Introduction", parts[0].strip()))
    for i in range(1, len(parts) - 1, 2):
        sections.append((parts[i].strip(), parts[i + 1].strip()))

    chunks = []
    for section, body in sections:
        if not body:
            continue
        pieces = _split_long_section(body) if _approx_tokens(body) > MAX_TOKENS else [body]
        for j, piece in enumerate(pieces):
            slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")[:40]
            chunks.append({
                "id": f"{doc_title}#{slug}#p{j}",
                # Prepend the section heading so the embedding carries structure
                "text": f"{section}\n{piece}",
                "metadata": {"doc_title": title, "section": section, "language": language},
            })
    return chunks
