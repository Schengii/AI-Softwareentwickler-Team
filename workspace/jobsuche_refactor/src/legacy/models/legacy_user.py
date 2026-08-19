# src/legacy/models/legacy_user.py
from dataclasses import dataclass

@dataclass
class LegacyUser:
    """Altes Daten‑Objekt – bleibt unverändert, weil es von externen Systemen genutzt wird."""
    id: str
    name: str
    role: str
