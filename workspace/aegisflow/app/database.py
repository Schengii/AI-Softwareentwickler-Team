# Proxy to maintain backward compatibility while fulfilling the interface contract
from app.storage.database import Base, async_session_maker, engine, get_db

# Alias for existing code that might still use the old name
get_async_session = get_db

__all__ = ["Base", "engine", "get_db", "get_async_session", "async_session_maker"]
