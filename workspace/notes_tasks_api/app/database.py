from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.orm import sessionmaker

# SQLite Datenbank, Datei im Projektverzeichnis
DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL, echo=False)

# Session factory für Dependency Injection
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

def get_db():
    """FastAPI Dependency, liefert eine DB-Session und schließt sie nach Request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
