from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import database, models


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Datenbanktabellen erstellen
    models.Base.metadata.create_all(bind=database.engine)
    yield
    # Shutdown

app = FastAPI(title="Snippet Vault API", lifespan=lifespan)

# Security: CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion auf spezifische Domains einschränken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SnippetCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    language: str = Field(..., min_length=1, max_length=50)
    tags: list[str] = []

@app.get("/snippets")
def read_snippets(q: str | None = None, tag: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Snippet)
    if q:
        query = query.filter(models.Snippet.content.contains(q))
    if tag:
        query = query.join(models.Snippet.tags).filter(models.Tag.name == tag)
    return query.all()

@app.post("/snippets")
def create_snippet(snippet: SnippetCreate, db: Session = Depends(get_db)):
    db_snippet = models.Snippet(title=snippet.title, content=snippet.content, language=snippet.language)
    # Tags aus dem Request-Body wurden bisher nie mit dem Snippet verknüpft (das
    # SnippetCreate.tags-Feld existierte, wurde hier aber schlicht ignoriert) - jeder
    # übermittelte Tag verschwand dadurch stillschweigend: /tags blieb immer leer und die
    # Tag-Filterung über ?tag=... in read_snippets() konnte nie etwas finden. Bestehende
    # Tags (per Name) werden wiederverwendet statt dupliziert, neue werden angelegt.
    for tag_name in snippet.tags:
        tag = db.query(models.Tag).filter(models.Tag.name == tag_name).first()
        if tag is None:
            tag = models.Tag(name=tag_name)
            db.add(tag)
        db_snippet.tags.append(tag)
    db.add(db_snippet)
    db.commit()
    db.refresh(db_snippet)
    return db_snippet

@app.get("/tags")
def read_tags(db: Session = Depends(get_db)):
    return db.query(models.Tag).all()
