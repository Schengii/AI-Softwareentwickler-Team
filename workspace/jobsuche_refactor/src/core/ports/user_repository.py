# src/core/ports/user_repository.py
from abc import ABC, abstractmethod
from uuid import UUID
from ..entities.user import User

class UserRepository(ABC):
    """Port – definiert das Interface für Persistenz‑Adapter."""

    @abstractmethod
    async def add(self, user: User) -> None: ...
    @abstractmethod
    async def get(self, user_id: UUID) -> User | None: ...
