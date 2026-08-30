from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session, select

# Datenbank-Konfiguration (wird später über Umgebungsvariablen geladen)
DATABASE_URL = "postgresql://user:password@localhost/kanban"

class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    status: str  # z.B. "todo", "in_progress", "done"

engine = create_engine(DATABASE_URL)

def init_db():
    SQLModel.metadata.create_all(engine)
