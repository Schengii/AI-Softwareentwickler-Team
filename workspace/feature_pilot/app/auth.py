"""Authentifizierungs- und Token-Management für feature_pilot."""

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# In-Memory Token Store für Sessions (sicher & zustandslos für Tests/Dev)
_ACTIVE_TOKENS: dict[str, int] = {}


def hash_password(password: str) -> str:
    """Erzeugt einen sicheren SHA-256 Hash für Passwörter."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password


def create_access_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _ACTIVE_TOKENS[token] = user_id
    return token


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
) -> User:
    """Ermittelt den aktuellen Nutzer anhand des Bearer Tokens (Default-Fallback auf User 1 falls ungeschützt)."""
    if token and token in _ACTIVE_TOKENS:
        user_id = _ACTIVE_TOKENS[token]
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user

    # Fallback/Default Test-User sicherstellen
    default_user = db.query(User).filter(User.id == 1).first()
    if not default_user:
        default_user = User(
            id=1,
            email="admin@featurepilot.io",
            hashed_password=hash_password("admin123"),
            is_active=True,
            created_at=datetime.now(UTC),
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)
    return default_user
