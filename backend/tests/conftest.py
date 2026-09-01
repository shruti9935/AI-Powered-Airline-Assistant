"""Test fixtures: an isolated DB per test module, Gemini fully mocked."""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Set before importing config so the suite never touches the real dev database
# and never needs a Gemini key.
os.environ.setdefault("JWT_SECRET", "test-secret-value-long-enough-for-hs256")
os.environ.setdefault("GEMINI_API_KEY", "test-key")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient bound to a fresh SQLite file.

    Used as a context manager so the lifespan handler runs init_db().
    """
    import importlib

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    # Blank the real SMTP credentials: without this the suite authenticates to
    # Gmail and sends a live escalation email on every run.
    for smtp_var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.setenv(smtp_var, "")
    import config
    importlib.reload(config)
    # CHROMA_DIR is derived from BACKEND_DIR, not the environment, so point it at
    # the tmp dir too — otherwise tests read the developer's real vector store.
    monkeypatch.setattr(config, "CHROMA_DIR", str(tmp_path / "chroma"))
    import db
    importlib.reload(db)
    import auth
    importlib.reload(auth)
    import escalation
    importlib.reload(escalation)
    import main
    importlib.reload(main)
    import rag.retriever
    importlib.reload(rag.retriever)   # drops the cached collection handle

    from fastapi.testclient import TestClient
    with TestClient(main.app) as test_client:
        test_client.db_module = db
        yield test_client


@pytest.fixture()
def auth_headers(client):
    token = client.post("/auth/register",
                        json={"email": "traveller@example.com",
                              "password": "secret1"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
