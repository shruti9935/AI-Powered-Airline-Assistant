"""Embed the query and pull the top-k most similar chunks from ChromaDB."""
from typing import Dict, List

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


def retrieve(query: str, top_k: int = config.TOP_K) -> List[Dict]:
    """Return [{id, text, section, similarity}] sorted by similarity desc."""
    collection = _get_collection()
    if collection.count() == 0:
        return []
    query_embedding = embed_texts([query], for_query=True)[0]
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for cid, doc, meta, dist in zip(result["ids"][0], result["documents"][0],
                                    result["metadatas"][0], result["distances"][0]):
        hits.append({
            "id": cid,
            "text": doc,
            "section": meta.get("section", ""),
            "similarity": round(1.0 - dist, 4),   # cosine distance -> similarity
        })
    return hits
