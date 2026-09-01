"""AI-Powered Airline Assistant — FastAPI backend.

Run:  uvicorn main:app --reload      (from the backend/ directory)
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from auth import current_user, router as auth_router
from db import Conversation, Escalation, QueryLog, User, get_db, init_db
from escalation import escalate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI-Powered Airline Assistant", version="1.1.0",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth_router)


class ChatRequest(BaseModel):
    message: str
    language: str = "en"                       # en | hi | es | fr
    conversation_id: Optional[int] = None      # omit to start a new thread


class EscalateRequest(BaseModel):
    query_log_id: int
    reason: str = Field(default="user_requested", max_length=200)


def _get_conversation(conversation_id: Optional[int], user: User,
                      first_message: str, db: Session) -> Conversation:
    """Fetch this passenger's conversation, or open a new one."""
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if not conversation or conversation.user_id != user.id:
            raise HTTPException(404, "Conversation not found")
        return conversation
    conversation = Conversation(user_id=user.id, title=first_message[:120])
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _prior_turns(conversation: Conversation, db: Session) -> List[dict]:
    """The last few turns of this thread, oldest first, for model memory."""
    rows = (db.query(QueryLog)
            .filter(QueryLog.conversation_id == conversation.id)
            .order_by(QueryLog.id.desc()).limit(config.HISTORY_TURNS).all())
    return [{"query": r.query, "answer": r.answer} for r in reversed(rows)]


def _escalation_payload(esc, query_log: QueryLog, db: Session) -> dict:
    """What the passenger is told once a query reaches a human team."""
    from rag.generator import generate_escalation_notice
    from db import Department

    department = db.get(Department, esc.department_id)
    name = department.name if department else "support"
    return {
        "escalation_id": esc.id,
        "status": esc.status,
        "department": name,
        "sla_hours": config.ESCALATION_SLA_HOURS,
        "message": generate_escalation_notice(name, query_log.language),
    }


@app.get("/health")
def health():
    from rag.retriever import chunk_count
    indexed = chunk_count()
    return {
        "status": "ok",
        "gemini_key_set": bool(config.GEMINI_API_KEY),
        "indexed_chunks": indexed,
        # A zero here is the usual cause of "the bot escalates everything".
        "knowledge_base_ready": indexed > 0,
    }


@app.post("/chat")
def chat(req: ChatRequest, user: User = Depends(current_user),
         db: Session = Depends(get_db)):
    message = req.message.strip()
    if not message:
        raise HTTPException(422, "Message is empty")
    if len(message) > config.MAX_MESSAGE_CHARS:
        raise HTTPException(
            422, f"Message is too long (max {config.MAX_MESSAGE_CHARS} characters)")
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "GEMINI_API_KEY is not set — add it to .env and restart the backend.")

    # Import here so the app can start (and auth can be tested) without RAG deps ready
    from rag.generator import generate_answer
    from rag.retriever import retrieve

    conversation = _get_conversation(req.conversation_id, user, message, db)
    history = _prior_turns(conversation, db)

    try:
        chunks = retrieve(message)
    except Exception:
        log.exception("Retrieval failed")
        raise HTTPException(502, "Could not search the policy knowledge base. Please try again.")

    top_similarity = chunks[0]["similarity"] if chunks else 0.0

    try:
        result = generate_answer(message, chunks, req.language, history=history)
    except Exception:
        log.exception("Generation failed")
        raise HTTPException(502, "The assistant is temporarily unavailable. Please try again.")

    # Log the query, keeping the excerpts so an escalation email can show them.
    query_log = QueryLog(
        user_id=user.id, conversation_id=conversation.id, query=message,
        language=req.language, answer=result["answer"],
        retrieved_chunk_ids=json.dumps([c["id"] for c in chunks]),
        retrieved_context=json.dumps(chunks),
        top_similarity=top_similarity)
    db.add(query_log)
    db.commit()
    db.refresh(query_log)

    # Confidence gate → human-in-the-loop escalation.
    # Small talk and off-topic messages are handled conversationally — never escalated.
    kind = result["kind"]
    reason = None
    if kind == "no_answer":
        reason = "model_no_answer"
    elif kind == "grounded" and top_similarity < config.SIMILARITY_THRESHOLD:
        reason = f"low_similarity ({top_similarity:.2f} < {config.SIMILARITY_THRESHOLD})"

    escalated, escalation = False, None
    if reason:
        try:
            esc = escalate(user, query_log, reason, db)
            escalation = _escalation_payload(esc, query_log, db)
            escalated = True
        except Exception:
            # A routing or SMTP failure must not discard an answer we already have.
            log.exception("Escalation failed for query_log %s", query_log.id)
            db.rollback()

    show_sources = kind in ("grounded", "no_answer")
    return {
        "answer": result["answer"],
        "kind": kind,
        "sources": [{"id": c["id"], "section": c["section"],
                     "similarity": c["similarity"]} for c in chunks] if show_sources else [],
        "confidence": top_similarity,
        "escalated": escalated,
        "escalation": escalation,
        "query_log_id": query_log.id,
        "conversation_id": conversation.id,
    }


@app.get("/chat/history")
def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(QueryLog).filter(QueryLog.user_id == user.id)
            .order_by(QueryLog.created_at.desc()).limit(50).all())
    return [{
        "id": r.id, "conversation_id": r.conversation_id, "query": r.query,
        "language": r.language, "answer": r.answer,
        "top_similarity": r.top_similarity, "escalated": bool(r.escalated),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@app.get("/conversations")
def list_conversations(user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    rows = (db.query(Conversation).filter(Conversation.user_id == user.id)
            .order_by(Conversation.id.desc()).limit(50).all())
    return [{
        "id": c.id, "title": c.title, "turns": len(c.turns),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return {
        "id": conversation.id,
        "title": conversation.title,
        "turns": [{
            "query_log_id": t.id, "query": t.query, "answer": t.answer,
            "language": t.language, "confidence": t.top_similarity,
            "escalated": bool(t.escalated),
        } for t in conversation.turns],
    }


@app.post("/escalate")
def manual_escalate(req: EscalateRequest, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    query_log = db.get(QueryLog, req.query_log_id)
    if not query_log or query_log.user_id != user.id:
        raise HTTPException(404, "Query not found")
    existing = db.query(Escalation).filter(
        Escalation.query_log_id == query_log.id).first()
    if existing:
        return {**_escalation_payload(existing, query_log, db),
                "detail": "Already escalated"}
    try:
        esc = escalate(user, query_log, req.reason, db)
    except Exception:
        log.exception("Manual escalation failed for query_log %s", query_log.id)
        db.rollback()
        raise HTTPException(502, "Could not reach the escalation service. Please try again.")
    return _escalation_payload(esc, query_log, db)
