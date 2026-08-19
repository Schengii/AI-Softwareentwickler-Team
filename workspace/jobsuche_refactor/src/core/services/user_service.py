# src/core/services/user_service.py
from __future__ import annotations
from uuid import UUID
from typing import Protocol

from ..entities.user import User
from ..ports.user_repository import UserRepository

class ValidationError(Exception): ...

class UserValidator(Protocol):
    """Strategy‑Interface für Validierung (Dependency Inversion)."""
    def __call__(self, user: User) -> None: ...

def default_validator(user: User) -> None:
    if not user.name:
        raise ValidationError("Name must not be empty")
    if user.role not in ("admin", "regular", "guest"):
        raise ValidationError(f"Invalid role: {user.role}")

class UserService:
    """Orchestriert Use‑Case‑Logik, ist testbar und DI‑freundlich."""
    def __init__(
        self,
        repo: UserRepository,
        validator: UserValidator = default_validator,
    ) -> None:
        self._repo = repo
        self._validator = validator

    async def create_user(self, user: User) -> None:
        self._validator(user)          # <-- Validation
        await self._repo.add(user)     # <-- Persistence
