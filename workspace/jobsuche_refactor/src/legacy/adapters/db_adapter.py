# src/legacy/adapters/db_adapter.py
from __future__ import annotations
from typing import Any
import asyncio

# Simulierte Legacy‑Datenbank‑API (keine Typen)
def db_save(payload: Any) -> None:
    # In einer echten Anwendung würde hier ein DB‑Client aufgerufen.
    asyncio.get_event_loop().run_in_executor(None, lambda: print("saved:", payload))
