"""Gemini embedding helper shared by ingest and retrieval."""
from typing import List

from google import genai
from google.genai import types

import config

_client = None


def gemini_client() -> genai.Client:
    global _client
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Paste your Google AI Studio key into "
            "the .env file at the project root and restart.")
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def embed_texts(texts: List[str], for_query: bool = False) -> List[List[float]]:
    """Embed with gemini-embedding-001 (multilingual, 768-dim)."""
    task = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"
    result = gemini_client().models.embed_content(
        model=config.EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task, output_dimensionality=config.EMBEDDING_DIM),
    )
    return [e.values for e in result.embeddings]
