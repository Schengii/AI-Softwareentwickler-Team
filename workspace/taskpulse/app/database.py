from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
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

class Base(DeclarativeBase):
    pass

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
