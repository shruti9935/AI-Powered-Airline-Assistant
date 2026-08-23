"""Department routing + SMTP human-in-the-loop escalation.

If SMTP is not configured, the escalation is still recorded in MySQL/SQLite
with status "pending_email" so no query is ever silently dropped.
"""
import logging
import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

import config
from db import Department, Escalation, QueryLog, User

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


def route_department(query: str, db: Session) -> Department:
    """Classify the query into a department by multilingual keyword rules."""
    q = query.lower()
    for dept_name, keywords in DEPARTMENT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return db.query(Department).filter(Department.name == dept_name).one()
    return db.query(Department).filter(Department.name == DEFAULT_DEPARTMENT).one()


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
    """Route to a department, email it (if SMTP configured), record the escalation."""
    dept = route_department(query_log.query, db)
    body = (
        "A passenger query could not be resolved by the AI assistant.\n\n"
        "Passenger: {email}\nLanguage: {lang}\nReason: {reason}\n\n"
        "Query:\n{query}\n\nAssistant answer (if any):\n{answer}\n"
    ).format(email=user.email, lang=query_log.language, reason=reason,
             query=query_log.query, answer=query_log.answer or "-")
    emailed = _send_email(dept.email, "[Escalation] SkyWings AI Assistant", body)

    esc = Escalation(
        user_id=user.id, query_log_id=query_log.id, department_id=dept.id,
        reason=reason, status="emailed" if emailed else "pending_email")
    db.add(esc)
    query_log.escalated = 1
    db.commit()
    db.refresh(esc)
    log.info("Escalated query %s to %s (%s)", query_log.id, dept.name, esc.status)
    return esc
