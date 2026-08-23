"""Register / login with bcrypt-hashed passwords and JWT sessions."""
from datetime import datetime, timedelta

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


class Credentials(BaseModel):
    email: EmailStr
    password: str


def _make_token(user: User) -> str:
    payload = {"sub": str(user.id), "email": user.email,
               "exp": datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


@router.post("/register")
def register(creds: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == creds.email).first():
        raise HTTPException(409, "An account with this email already exists")
    if len(creds.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    pw_hash = bcrypt.hashpw(creds.password.encode(), bcrypt.gensalt()).decode()
    user = User(email=creds.email, password_hash=pw_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": _make_token(user), "token_type": "bearer"}


@router.post("/login")
def login(creds: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == creds.email).first()
    if not user or not bcrypt.checkpw(creds.password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": _make_token(user), "token_type": "bearer"}


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security),
                 db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(credentials.credentials, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User no longer exists")
    return user
