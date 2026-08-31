from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from . import models, database
from pydantic import BaseModel, Field
from typing import List, Optional
from contextlib import asynccontextmanager

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
    tags: List[str] = []

@app.get("/snippets")
def read_snippets(q: Optional[str] = None, tag: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Snippet)
    if q:
        query = query.filter(models.Snippet.content.contains(q))
    if tag:
        query = query.join(models.Snippet.tags).filter(models.Tag.name == tag)
    return query.all()

@app.post("/snippets")
def create_snippet(snippet: SnippetCreate, db: Session = Depends(get_db)):
    db_snippet = models.Snippet(title=snippet.title, content=snippet.content, language=snippet.language)
    db.add(db_snippet)
    db.commit()
    db.refresh(db_snippet)
    return db_snippet
