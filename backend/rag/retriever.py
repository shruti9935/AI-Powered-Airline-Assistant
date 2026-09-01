"""Embed the query and pull the top-k most similar chunks from ChromaDB."""
from typing import Dict, List, Optional

import chromadb

import config
from rag.embeddings import embed_texts

_collection = None


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        _collection = client.get_or_create_collection(
            name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    return _collection


def chunk_count() -> int:
    """Number of indexed chunks — 0 means `python rag/ingest.py` never ran."""
    try:
        return _get_collection().count()
    except Exception:
        return 0


def retrieve(query: str, top_k: int = None,
             where: Optional[Dict] = None) -> List[Dict]:
    """Return [{id, text, section, similarity}] sorted by similarity desc.

    ``where`` is an optional ChromaDB metadata filter, e.g.
    ``{"source": "airline-rules"}`` or ``{"language": "en"}``.
    """
    top_k = top_k or config.TOP_K
    collection = _get_collection()
    total = collection.count()
    if total == 0:
        return []
    query_embedding = embed_texts([query], for_query=True)[0]
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, total),
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    if not result["ids"] or not result["ids"][0]:
        return []
    hits = []
    for cid, doc, meta, dist in zip(result["ids"][0], result["documents"][0],
                                    result["metadatas"][0], result["distances"][0]):
        meta = meta or {}
        hits.append({
            "id": cid,
            "text": doc,
            "source": meta.get("source", ""),
            "section": meta.get("section", ""),
            "similarity": round(1.0 - dist, 4),   # cosine distance -> similarity
        })
    return hits
