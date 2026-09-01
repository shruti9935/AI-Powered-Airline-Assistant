"""Gemini embedding helper shared by ingest and retrieval."""
import logging
import math
import time
from typing import List

from google import genai
from google.genai import types

import config

log = logging.getLogger("embeddings")

_client = None

MAX_BATCH = 100          # API limit per embed_content call
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5


def gemini_client() -> genai.Client:
    global _client
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Paste your Google AI Studio key into "
            "the .env file at the project root and restart.")
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def _embed_batch(texts: List[str], task: str) -> List[List[float]]:
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            result = gemini_client().models.embed_content(
                model=config.EMBEDDING_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type=task, output_dimensionality=config.EMBEDDING_DIM),
            )
            return [e.values for e in result.embeddings]
        except Exception as exc:                      # transient API/network error
            last_error = exc
            if attempt == MAX_RETRIES - 1:
                break
            wait = RETRY_BACKOFF_SECONDS * (2 ** attempt)
            log.warning("Embedding call failed (%s); retrying in %.1fs", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Embedding failed after {MAX_RETRIES} attempts: {last_error}")


def embed_texts(texts: List[str], for_query: bool = False) -> List[List[float]]:
    """Embed with gemini-embedding-001 (multilingual, 768-dim by default)."""
    if not texts:
        return []
    task = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"

    vectors = []
    for i in range(0, len(texts), MAX_BATCH):
        vectors.extend(_embed_batch(texts[i:i + MAX_BATCH], task))

    # gemini-embedding-001 only returns unit-length vectors at its native 3072
    # dimensions; truncated outputs must be normalized by the caller.
    if config.EMBEDDING_DIM != 3072:
        vectors = [_normalize(v) for v in vectors]
    return vectors
