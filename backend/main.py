"""AI-Powered Airline Assistant — FastAPI backend.

Run:  uvicorn main:app --reload      (from the backend/ directory)
"""
import json
import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

import config
from auth import current_user, router as auth_router
from db import Escalation, QueryLog, User, get_db, init_db
from escalation import escalate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

app = FastAPI(title="AI-Powered Airline Assistant", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth_router)
init_db()


class ChatRequest(BaseModel):
    message: str
    language: str = "en"          # en | hi | es | fr


class EscalateRequest(BaseModel):
    query_log_id: int
    reason: str = "user_requested"


@app.get("/health")
def health():
    return {"status": "ok", "gemini_key_set": bool(config.GEMINI_API_KEY)}


@app.post("/chat")
def chat(req: ChatRequest, user: User = Depends(current_user),
         db: Session = Depends(get_db)):
    if not req.message.strip():
        raise HTTPException(422, "Message is empty")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "GEMINI_API_KEY is not set — add it to .env and restart the backend.")

    # Import here so the app can start (and auth can be tested) without RAG deps ready
    from rag.generator import generate_answer
    from rag.retriever import retrieve

    try:
        chunks = retrieve(req.message)
    except Exception as exc:
        log.exception("Retrieval failed")
        raise HTTPException(502, f"Retrieval failed: {exc}")

    top_similarity = chunks[0]["similarity"] if chunks else 0.0

    try:
        result = generate_answer(req.message, chunks, req.language)
    except Exception as exc:
        log.exception("Generation failed")
        raise HTTPException(502, f"Generation failed: {exc}")

    # Log the query
    query_log = QueryLog(
        user_id=user.id, query=req.message, language=req.language,
        answer=result["answer"],
        retrieved_chunk_ids=json.dumps([c["id"] for c in chunks]),
        top_similarity=top_similarity)
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    # Confidence gate → human-in-the-loop escalation.
    # Small talk and off-topic messages are handled conversationally — never escalated.
    kind = result["kind"]
    escalated = False
    if kind == "no_answer":
        escalate(user, query_log, "model_no_answer", db)
        escalated = True
    elif kind == "grounded" and top_similarity < config.SIMILARITY_THRESHOLD:
        escalate(user, query_log,
                 f"low_similarity ({top_similarity:.2f} < {config.SIMILARITY_THRESHOLD})", db)
        escalated = True

    show_sources = kind in ("grounded", "no_answer")
    return {
        "answer": result["answer"],
        "kind": kind,
        "sources": [{"id": c["id"], "section": c["section"],
                     "similarity": c["similarity"]} for c in chunks] if show_sources else [],
        "confidence": top_similarity,
        "escalated": escalated,
        "query_log_id": query_log.id,
    }


@app.get("/chat/history")
def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(QueryLog).filter(QueryLog.user_id == user.id)
            .order_by(QueryLog.created_at.desc()).limit(50).all())
    return [{
        "id": r.id, "query": r.query, "language": r.language, "answer": r.answer,
        "top_similarity": r.top_similarity, "escalated": bool(r.escalated),
        "created_at": r.created_at.isoformat(),
    } for r in rows]


@app.post("/escalate")
def manual_escalate(req: EscalateRequest, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    query_log = db.get(QueryLog, req.query_log_id)
    if not query_log or query_log.user_id != user.id:
        raise HTTPException(404, "Query not found")
    existing = db.query(Escalation).filter(
        Escalation.query_log_id == query_log.id).first()
    if existing:
        return {"escalation_id": existing.id, "status": existing.status,
                "detail": "Already escalated"}
    esc = escalate(user, query_log, req.reason, db)
    return {"escalation_id": esc.id, "status": esc.status}
