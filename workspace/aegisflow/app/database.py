"""Database proxy module providing re-exports from app.storage.database.

Ensures backward compatibility and consistency across all models and consumers.
"""

from typing import Any, Callable

from app.storage.database import (
    Base as _Base,
    async_session_maker as _async_session_maker,
    engine as _engine,
    get_db as _get_db,
)

# Explicit top-level bindings for static analyzers (AST checks) and runtime imports
Base = _Base
engine = _engine
async_session_maker = _async_session_maker
get_db: Callable[..., Any] = _get_db
get_async_session: Callable[..., Any] = _get_db

__all__ = [
    "Base",
    "engine",
    "get_db",
    "get_async_session",
    "async_session_maker",
]
