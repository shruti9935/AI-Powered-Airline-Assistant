"""Department routing + SMTP human-in-the-loop escalation.

If SMTP is not configured, the escalation is still recorded in MySQL/SQLite
with status "pending_email" so no query is ever silently dropped.
"""
import json
import logging
import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

import config
from db import Department, Escalation, QueryLog, User, seed_departments

log = logging.getLogger("escalation")

# Multilingual keyword rules per department (en / hi / es / fr)
DEPARTMENT_KEYWORDS = {
    "Baggage Services": [
        "baggage", "luggage", "bag", "suitcase",
        "सामान", "बैग", "equipaje", "maleta", "bagage", "valise",
    ],
    "Refunds Desk": [
        "refund", "cancel", "cancellation", "money back", "reimburse",
        "रिफंड", "रद्द", "पैसे", "reembolso", "cancelar", "remboursement", "annul",
    ],
    "Special Assistance": [
        "wheelchair", "minor", "pet", "dog", "cat", "medical", "pregnan", "assist",
        "व्हीलचेयर", "पालतू", "silla de ruedas", "mascota", "fauteuil roulant", "animal",
    ],
}
DEFAULT_DEPARTMENT = "General Support"
TRANSCRIPT_TURNS = 20


def _department_by_name(name: str, db: Session) -> Department:
    """Look up a department, re-seeding if the table was never populated.

    Previously a `.one()` here raised NoResultFound and took down an otherwise
    successful /chat response.
    """
    dept = db.query(Department).filter(Department.name == name).one_or_none()
    if dept is None:
        seed_departments(db)
        dept = db.query(Department).filter(Department.name == name).one_or_none()
    return dept


def route_department(query: str, db: Session) -> Department:
    """Classify the query into a department by multilingual keyword rules."""
    q = (query or "").lower()
    for dept_name, keywords in DEPARTMENT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            dept = _department_by_name(dept_name, db)
            if dept:
                return dept
    dept = _department_by_name(DEFAULT_DEPARTMENT, db)
    if dept is None:
        raise RuntimeError("No departments configured — cannot route escalation.")
    return dept


def _render_transcript(query_log: QueryLog, db: Session) -> str:
    """The whole conversation thread, oldest first."""
    if query_log.conversation_id is None:
        turns = [query_log]
    else:
        turns = (db.query(QueryLog)
                 .filter(QueryLog.conversation_id == query_log.conversation_id)
                 .order_by(QueryLog.id).limit(TRANSCRIPT_TURNS).all())
    lines = []
    for turn in turns:
        marker = "  <-- escalated" if turn.id == query_log.id else ""
        lines.append(f"Passenger: {turn.query}{marker}")
        lines.append(f"Assistant: {turn.answer or '-'}")
        lines.append("")
    return "\n".join(lines).strip()


def _render_context(query_log: QueryLog) -> str:
    """The policy excerpts the assistant actually retrieved for this turn."""
    if not query_log.retrieved_context:
        return "(no excerpts retrieved)"
    try:
        chunks = json.loads(query_log.retrieved_context)
    except json.JSONDecodeError:
        return "(context unavailable)"
    if not chunks:
        return "(no excerpts retrieved)"
    return "\n\n".join(
        "[{0} | {1}] similarity {2}\n{3}".format(
            c.get("id", "?"), c.get("section", "?"), c.get("similarity", "?"),
            c.get("text", ""))
        for c in chunks)


def build_email_body(user: User, query_log: QueryLog, reason: str, db: Session) -> str:
    return (
        "A passenger query could not be resolved by the AI assistant.\n\n"
        f"Passenger: {user.email}\n"
        f"Language: {query_log.language}\n"
        f"Reason: {reason}\n"
        f"Confidence: {query_log.top_similarity}\n"
        f"Conversation: #{query_log.conversation_id}\n\n"
        "--- CONVERSATION TRANSCRIPT ---\n"
        f"{_render_transcript(query_log, db)}\n\n"
        "--- RETRIEVED POLICY CONTEXT ---\n"
        f"{_render_context(query_log)}\n"
    )


def _send_email(to_addr: str, subject: str, body: str) -> bool:
    if not (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD):
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as exc:
        log.warning("SMTP send failed: %s", exc)
        return False


def escalate(user: User, query_log: QueryLog, reason: str, db: Session) -> Escalation:
    """Route to a department, email it (if SMTP configured), record the escalation.

    Idempotent: an already-escalated query returns its existing record.
    """
    existing = (db.query(Escalation)
                .filter(Escalation.query_log_id == query_log.id).one_or_none())
    if existing:
        return existing

    dept = route_department(query_log.query, db)
    body = build_email_body(user, query_log, reason, db)
    emailed = _send_email(dept.email, "[Escalation] SkyWings AI Assistant", body)

    esc = Escalation(
        user_id=user.id, query_log_id=query_log.id, department_id=dept.id,
        reason=reason, detail=body,
        status="emailed" if emailed else "pending_email")
    db.add(esc)
    query_log.escalated = 1
    db.commit()
    db.refresh(esc)
    log.info("Escalated query %s to %s (%s)", query_log.id, dept.name, esc.status)
    return esc
