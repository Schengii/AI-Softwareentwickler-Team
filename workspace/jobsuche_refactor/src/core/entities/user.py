# src/core/entities/user.py
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from typing import Literal

UserRole = Literal["admin", "regular", "guest"]

@dataclass(frozen=True, slots=True)
class User:
    """Domain‑Entity – pure Daten‑Container."""
    id: UUID
    name: str
    role: UserRole
