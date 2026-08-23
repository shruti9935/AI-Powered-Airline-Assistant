"""Central configuration — loads .env from the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent   # airline-chatbot/
BACKEND_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./airline.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()

# RAG settings
CHROMA_DIR = str(BACKEND_DIR / "chroma_db")
COLLECTION_NAME = "airline_docs"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
CHAT_MODEL = "gemini-3.6-flash"
TOP_K = 5
SIMILARITY_THRESHOLD = 0.55   # below this → escalate

DOCS_DIR = ROOT_DIR / "docs"

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French"}
