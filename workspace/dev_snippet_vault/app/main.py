import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_db
from app.models import Snippet
from app.schemas import SnippetCreate, SnippetOut, SnippetUpdate
from app.security import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB-Tabellen asynchron anlegen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Stelle sicher, dass das public-Verzeichnis existiert
    os.makedirs("public", exist_ok=True)
    if not os.path.exists("public/index.html"):
        with open("public/index.html", "w") as f:
            f.write("<html><body><h1>Dev Snippet Vault</h1></body></html>")
            
    yield
    await engine.dispose()

app = FastAPI(title="Dev Snippet Vault", lifespan=lifespan)

app.add_middleware(SecurityHeadersMiddleware)
@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/api/snippets", response_model=SnippetOut)
async def create_snippet(snippet: SnippetCreate, db: AsyncSession = Depends(get_db)):
    db_snippet = Snippet(**snippet.model_dump())
    db.add(db_snippet)
    await db.commit()
    await db.refresh(db_snippet)
    return db_snippet

@app.get("/api/snippets", response_model=list[SnippetOut])
async def get_snippets(
    q: str | None = None,
    language: str | None = None,
    is_favorite: bool | None = None,
    db: AsyncSession = Depends(get_db)
):
    if q:
        # FTS5 Volltextsuche
        query = text("SELECT rowid FROM snippets_fts WHERE snippets_fts MATCH :q")
        fts_result = await db.execute(query, {"q": q})
        rowids = [row[0] for row in fts_result.fetchall()]
        
        if not rowids:
            return []
            
        stmt = select(Snippet).where(Snippet.id.in_(rowids))
    else:
        stmt = select(Snippet)
        
    if language:
        stmt = stmt.where(Snippet.language == language)
    if is_favorite is not None:
        stmt = stmt.where(Snippet.is_favorite == is_favorite)
        
    result = await db.execute(stmt)
    return result.scalars().all()

@app.get("/api/snippets/{snippet_id}", response_model=SnippetOut)
async def get_snippet(snippet_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    snippet = result.scalar_one_or_none()
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return snippet

@app.put("/api/snippets/{snippet_id}", response_model=SnippetOut)
async def update_snippet(snippet_id: int, snippet_update: SnippetUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    db_snippet = result.scalar_one_or_none()
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    
    update_data = snippet_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_snippet, key, value)
        
    await db.commit()
    await db.refresh(db_snippet)
    return db_snippet

@app.delete("/api/snippets/{snippet_id}")
async def delete_snippet(snippet_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Snippet).where(Snippet.id == snippet_id))
    db_snippet = result.scalar_one_or_none()
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    
    await db.delete(db_snippet)
    await db.commit()
    return {"status": "deleted"}

@app.get("/api/tags", response_model=list[str])
async def get_tags(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Snippet.tags).where(Snippet.tags.isnot(None)))
    tags_list = result.scalars().all()
    
    unique_tags = set()
    for tags_str in tags_list:
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip()
                if tag:
                    unique_tags.add(tag)
                    
    return sorted(list(unique_tags))

# Statische Dateien mounten (MUSS nach den API-Routen erfolgen)
app.mount("/", StaticFiles(directory="public", html=True), name="public")
