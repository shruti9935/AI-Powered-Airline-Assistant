"""SQLAlchemy models + session. SQLite by default, MySQL via DATABASE_URL."""
from datetime import datetime

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, String,
                        Text, create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    description = Column(String(255))


class QueryLog(Base):
    __tablename__ = "query_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query = Column(Text, nullable=False)
    language = Column(String(8), default="en")
    answer = Column(Text)
    retrieved_chunk_ids = Column(Text)          # JSON list of chunk ids
    top_similarity = Column(Float)
    escalated = Column(Integer, default=0)      # 0/1 (portable across SQLite/MySQL)
    created_at = Column(DateTime, default=datetime.utcnow)


class Escalation(Base):
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_log_id = Column(Integer, ForeignKey("query_logs.id"))
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    reason = Column(String(255))
    status = Column(String(32), default="pending_email")  # pending_email | emailed
    created_at = Column(DateTime, default=datetime.utcnow)


DEPARTMENTS = [
    ("Baggage Services", "baggage@skywings.example", "Lost / delayed / damaged baggage"),
    ("Refunds Desk", "refunds@skywings.example", "Refund status, cancellation disputes"),
    ("Special Assistance", "care@skywings.example", "Wheelchair, UM, pets, medical"),
    ("General Support", "support@skywings.example", "All other queries"),
]


def init_db():
    """Create tables and seed the four departments."""
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.query(Department).count() == 0:
            for name, email, desc in DEPARTMENTS:
                session.add(Department(name=name, email=email, description=desc))
            session.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
