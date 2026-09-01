"""Central configuration — loads .env from the project root.

Every setting goes through ``_env`` because ``os.getenv(name, default)`` does
NOT fall back when the variable is present but empty — which is exactly what
copying ``.env.example`` produces.
"""
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("config")

ROOT_DIR = Path(__file__).resolve().parent.parent   # airline-chatbot/
BACKEND_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating an empty/whitespace value as unset."""
    return (os.getenv(name) or "").strip() or default


def _dev_jwt_secret() -> str:
    """Generate and persist a dev secret so sessions survive --reload."""
    secret_file = BACKEND_DIR / ".dev_jwt_secret"
    if secret_file.exists():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    secret = secrets.token_urlsafe(48)
    secret_file.write_text(secret, encoding="utf-8")
    log.warning(
        "JWT_SECRET is not set — generated a development secret at %s. "
        "Set JWT_SECRET in .env before deploying anywhere real.", secret_file)
    return secret


GEMINI_API_KEY = _env("GEMINI_API_KEY")
DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'airline.db').as_posix()}")
JWT_SECRET = _env("JWT_SECRET") or _dev_jwt_secret()

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")

# Where escalations are emailed. The defaults are placeholders on a reserved
# example domain; override them in .env to route to real inboxes without
# putting anyone's address in the repository.
DEPARTMENT_EMAILS = {
    "Baggage Services": _env("BAGGAGE_EMAIL", "baggage@skywings.example"),
    "Refunds Desk": _env("REFUNDS_EMAIL", "refunds@skywings.example"),
    "Special Assistance": _env("SPECIAL_ASSISTANCE_EMAIL", "care@skywings.example"),
    "General Support": _env("SUPPORT_EMAIL", "support@skywings.example"),
}

# RAG settings
CHROMA_DIR = str(BACKEND_DIR / "chroma_db")
COLLECTION_NAME = "airline_docs"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
CHAT_MODEL = _env("CHAT_MODEL", "gemini-3.6-flash")
TOP_K = 5
SIMILARITY_THRESHOLD = 0.55   # below this → escalate

DOCS_DIR = ROOT_DIR / "docs"

# API limits / behaviour
MAX_MESSAGE_CHARS = int(_env("MAX_MESSAGE_CHARS", "2000"))
HISTORY_TURNS = int(_env("HISTORY_TURNS", "6"))    # prior turns sent to the model
CORS_ORIGINS = [o.strip() for o in _env(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

# Response time promised to the passenger when a query reaches a human team.
ESCALATION_SLA_HOURS = int(_env("ESCALATION_SLA_HOURS", "24"))

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French"}
