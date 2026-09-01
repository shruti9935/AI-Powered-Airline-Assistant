"""Register / login with bcrypt-hashed passwords and JWT sessions."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

import config
from db import User, get_db

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

TOKEN_TTL_HOURS = 12
MIN_PASSWORD_CHARS = 6
MAX_PASSWORD_BYTES = 72     # hard limit of the bcrypt algorithm


class Credentials(BaseModel):
    email: EmailStr
    password: str


def _make_token(user: User) -> str:
    payload = {"sub": str(user.id), "email": user.email,
               "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def _validate_password(password: str) -> bytes:
    """Return the encoded password, or raise 422 if bcrypt cannot hash it.

    bcrypt >= 4.2 raises ValueError past 72 bytes instead of truncating, so the
    limit is enforced here — note a short emoji password can exceed it.
    """
    if len(password) < MIN_PASSWORD_CHARS:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD_CHARS} characters")
    encoded = password.encode()
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            422, f"Password must be at most {MAX_PASSWORD_BYTES} bytes "
                 "(fewer characters if it contains emoji or non-Latin script)")
    return encoded


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security),
                 db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(credentials.credentials, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    subject = payload.get("sub")
    if subject is None or not str(subject).isdigit():
        raise HTTPException(401, "Invalid token")
    user = db.get(User, int(subject))
    if not user:
        raise HTTPException(401, "User no longer exists")
    return user


@router.post("/register")
def register(creds: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == creds.email).first():
        raise HTTPException(409, "An account with this email already exists")
    encoded = _validate_password(creds.password)
    pw_hash = bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()
    user = User(email=creds.email, password_hash=pw_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": _make_token(user), "token_type": "bearer"}


@router.post("/login")
def login(creds: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == creds.email).first()
    valid = False
    if user:
        try:
            valid = bcrypt.checkpw(creds.password.encode(), user.password_hash.encode())
        except ValueError:
            # Over-long password: it can never match a stored hash — 401, not 500.
            valid = False
    if not valid:
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": _make_token(user), "token_type": "bearer"}


@router.get("/me")
def whoami(user: User = Depends(current_user)):
    """Cheap token check — the frontend calls this on startup."""
    return {"id": user.id, "email": user.email}
