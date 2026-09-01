"""SQLAlchemy models + session. SQLite by default, MySQL via DATABASE_URL."""
import logging
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, create_engine, inspect, text)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

import config

log = logging.getLogger("db")

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    description = Column(String(255))


class Conversation(Base):
    """A chat thread. Groups query_logs so the model has multi-turn memory and
    escalation emails can carry a real transcript."""
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255))                 # first user message, truncated
    created_at = Column(DateTime, default=_utcnow)

    turns = relationship("QueryLog", back_populates="conversation",
                         order_by="QueryLog.id")


class QueryLog(Base):
    __tablename__ = "query_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    query = Column(Text, nullable=False)
    language = Column(String(8), default="en")
    answer = Column(Text)
    retrieved_chunk_ids = Column(Text)          # JSON list of chunk ids
    retrieved_context = Column(Text)            # JSON list of {id, section, text}
    top_similarity = Column(Float)
    escalated = Column(Integer, default=0)      # 0/1 (portable across SQLite/MySQL)
    created_at = Column(DateTime, default=_utcnow)

    conversation = relationship("Conversation", back_populates="turns")


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (UniqueConstraint("query_log_id", name="uq_escalation_query_log"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_log_id = Column(Integer, ForeignKey("query_logs.id"))
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    reason = Column(String(255))
    status = Column(String(32), default="pending_email")  # pending_email | emailed
    detail = Column(Text)                       # email body actually composed
    created_at = Column(DateTime, default=_utcnow)


# Contact addresses live in config so a deployment can point them at real
# inboxes through .env instead of hardcoding anyone's address here.
DEPARTMENTS = [
    ("Baggage Services", "Lost / delayed / damaged baggage"),
    ("Refunds Desk", "Refund status, cancellation disputes"),
    ("Special Assistance", "Wheelchair, UM, pets, medical"),
    ("General Support", "All other queries"),
]

# Columns added after the first release — create_all() will not add them to an
# existing dev database, so patch them in rather than forcing a wipe.
_ADDED_COLUMNS = {
    "query_logs": {
        "conversation_id": "INTEGER",
        "retrieved_context": "TEXT",
    },
    "escalations": {
        "detail": "TEXT",
    },
}


def _ensure_columns():
    inspector = inspect(engine)
    for table, columns in _ADDED_COLUMNS.items():
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl_type in columns.items():
            if name in existing:
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
            log.info("Added missing column %s.%s", table, name)


def seed_departments(session):
    """Insert missing departments and reconcile changed contact details.

    Routing addresses are configuration, so an edit to DEPARTMENTS must reach an
    existing database — otherwise escalations keep going to the old address.
    """
    existing = {d.name: d for d in session.query(Department).all()}
    changed = False
    for name, desc in DEPARTMENTS:
        email = config.DEPARTMENT_EMAILS[name]
        current = existing.get(name)
        if current is None:
            session.add(Department(name=name, email=email, description=desc))
            changed = True
        elif current.email != email or current.description != desc:
            log.info("Department %s: contact updated to %s", name, email)
            current.email, current.description = email, desc
            changed = True
    if changed:
        session.commit()


def init_db():
    """Create tables, patch in later-added columns, and seed the departments."""
    _ensure_columns()
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_departments(session)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
