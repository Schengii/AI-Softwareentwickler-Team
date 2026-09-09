"""SQLAlchemy declarative base for async usage."""

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declarative_base

# AsyncAttrs adds async support for ORM methods like .save()
Base = declarative_base(cls=AsyncAttrs)
