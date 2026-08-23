"""CLI: index docs/*.md and docs/*.pdf into the ChromaDB collection.

Usage:  python rag/ingest.py        (run from the backend/ directory)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on path

import chromadb
from pypdf import PdfReader

import config
from rag.chunking import chunk_markdown
from rag.embeddings import embed_texts

BATCH = 32


def load_documents():
    """Yield (doc_name, text) for every .md / .pdf in docs/."""
    for path in sorted(config.DOCS_DIR.iterdir()):
        if path.suffix == ".md":
            yield path.stem, path.read_text(encoding="utf-8")
        elif path.suffix == ".pdf":
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            yield path.stem, text


def main():
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    all_chunks = []
    for doc_name, text in load_documents():
        # Skip the PDF twin of the markdown source to avoid duplicate content
        if doc_name == "airline-rules-and-regulations":
            continue
        chunks = chunk_markdown(text, doc_title=doc_name)
        print(f"  {doc_name}: {len(chunks)} chunks")
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
