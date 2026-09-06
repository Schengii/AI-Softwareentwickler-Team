from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# Datenbank-Konfiguration
# Entscheidung: SQLite für initiale Entwicklung, da einfach zu handhaben und keine Server-Infrastruktur erforderlich.
# Bei Tests wird StaticPool verwendet, um In-Memory-Datenbanken über Threads hinweg konsistent zu halten.

connect_args = {"check_same_thread": False} if settings.USE_SQLITE else {}
poolclass = StaticPool if settings.USE_SQLITE and ":memory:" in settings.DATABASE_URL else None

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    poolclass=poolclass
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Legt alle in Base.metadata registrierten Tabellen an (idempotent)."""
    from app import models  # noqa: F401 - registriert die Modelle bei Base, bevor create_all laeuft
    Base.metadata.create_all(bind=engine)
