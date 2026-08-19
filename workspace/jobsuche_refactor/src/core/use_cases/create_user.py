# src/core/use_cases/create_user.py
from __future__ import annotations
from uuid import UUID
from ..services.user_service import UserService, User, ValidationError

async def execute(
    raw_json: str,
    service: UserService,
) -> None:
    """
    Entry‑Point für das äußere Interface (z. B. API‑Handler).
    Verantwortlich nur für Parsing & Fehler‑Mapping.
    """
    import json

    try:
        payload: dict = json.loads(raw_json)
        user = User(
            id=UUID(payload["id"]),
            name=payload["name"],
            role=payload["role"],
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Malformed payload: {exc}") from exc

    try:
        await service.create_user(user)
    except ValidationError as exc:
        raise ValueError(f"Validation failed: {exc}") from exc
