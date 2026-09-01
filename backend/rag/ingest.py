"""CLI: index docs/*.md, *.txt and *.pdf into the ChromaDB collection.

Usage:  python rag/ingest.py [--reset] [--allow-duplicates]
        (run from the backend/ directory)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on path

import chromadb
from pypdf import PdfReader

import config
from rag.chunking import chunk_markdown, chunk_pages
from rag.embeddings import embed_texts

BATCH = 32
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}

# Markdown keeps its heading structure, which the chunker exploits; PDF text is
# flattened on extraction. When two files carry the same policies, prefer the
# structured one — ordering by filename alone would decide this by accident.
SUFFIX_PRIORITY = {".md": 0, ".markdown": 0, ".txt": 1, ".pdf": 2}

# A document whose vocabulary is this well covered by already-indexed documents
# is treated as a restatement of them. The repo ships the same policies as both
# Markdown and PDF; indexing both would return the same policy twice in every
# top-k. Structured sources are read first (see SUFFIX_PRIORITY), so the
# heading-aware Markdown wins over its flattened PDF twin.
DUPLICATE_COVERAGE = 0.85
MIN_TOKENS_TO_COMPARE = 40      # too-short documents are not judged this way


def load_documents():
    """Yield (source_name, chunks) for every supported file in docs/."""
    paths = [p for p in config.DOCS_DIR.iterdir()
             if p.suffix.lower() in SUPPORTED_SUFFIXES]
    for path in sorted(paths, key=lambda p: (SUFFIX_PRIORITY[p.suffix.lower()], p.name)):
        suffix = path.suffix.lower()
        source = path.stem
        if suffix == ".pdf":
            pages = [page.extract_text() or "" for page in PdfReader(path).pages]
            yield source, chunk_pages(pages, source=source)
        else:
            yield source, chunk_markdown(path.read_text(encoding="utf-8"),
                                         doc_title=source)


def _tokens(text: str) -> set:
    return {w.strip(".,;:()[]\"'") for w in text.lower().split() if len(w) > 2}


def coverage(candidate: set, indexed: set) -> float:
    """Fraction of a document's vocabulary already present in the index."""
    if not candidate:
        return 1.0
    return len(candidate & indexed) / len(candidate)


def main():
    parser = argparse.ArgumentParser(description="Index docs/ into ChromaDB.")
    parser.add_argument("--reset", action="store_true",
                        help="delete the whole collection before indexing")
    parser.add_argument("--allow-duplicates", action="store_true",
                        help="index near-duplicate documents instead of skipping them")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    if args.reset:
        try:
            client.delete_collection(config.COLLECTION_NAME)
            print(f"Deleted collection '{config.COLLECTION_NAME}'.")
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    all_chunks, indexed_tokens = [], set()
    for source, chunks in load_documents():
        if not chunks:
            print(f"  {source}: no text extracted — skipped")
            continue

        doc_tokens = _tokens(" ".join(c["text"] for c in chunks))
        if not args.allow_duplicates and len(doc_tokens) >= MIN_TOKENS_TO_COMPARE:
            overlap = coverage(doc_tokens, indexed_tokens)
            if overlap >= DUPLICATE_COVERAGE:
                print(f"  {source}: skipped — {overlap:.0%} of its content is already "
                      "indexed from another document (--allow-duplicates to override)")
                continue

        print(f"  {source}: {len(chunks)} chunks")
        # Drop this document's previous chunks so renamed or deleted sections
        # stop polluting retrieval — upsert alone would leave them behind.
        try:
            collection.delete(where={"source": source})
        except Exception:
            pass
        indexed_tokens |= doc_tokens
        all_chunks.extend(chunks)

    if not all_chunks:
        print("No documents found in docs/ — nothing to ingest.")
        return

    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i + BATCH]
        embeddings = embed_texts([c["text"] for c in batch])
        collection.upsert(
            ids=[c["id"] for c in batch],
            embeddings=embeddings,
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
    print(f"Ingested {len(all_chunks)} chunks into '{config.COLLECTION_NAME}' "
          f"({collection.count()} total in collection).")


if __name__ == "__main__":
    main()
