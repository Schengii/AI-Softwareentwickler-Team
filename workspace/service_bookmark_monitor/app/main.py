"""FastAPI-Einstiegspunkt für service_bookmark_monitor.

Stellt REST-Endpunkte für das Monitoring von `Service`- und
`Bookmark`-Ressourcen bereit. Tabellen werden beim Start der App
(in der `lifespan`-Hook) angelegt.
"""
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, engine, get_db
from app.models import Bookmark, Service
from app.schemas import BookmarkCreate, BookmarkRead, ServiceCreate, ServiceRead


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    """Legt beim Start die Tabellen an (sqlite in-memory pro Verbindung)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Bookmark Monitor API", version="0.1.0", lifespan=lifespan)


async def _get_or_404(model: type[Service] | type[Bookmark], obj_id: int, db: AsyncSession) -> Any:
    """Lädt ein Objekt per Primärschlüssel oder liefert 404."""
    obj = await db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ressource nicht gefunden")
    return obj


@app.get("/health")
async def health() -> dict[str, str]:
    """Smoke-Check-Endpunkt für Liveness."""
    return {"status": "ok"}


# ----------------------------- Services -----------------------------


@app.post("/services", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(payload: ServiceCreate, db: AsyncSession = Depends(get_db)) -> Service:
    svc = Service(**payload.model_dump())
    db.add(svc)
    await db.commit()
    await db.refresh(svc)
    return svc


@app.get("/services", response_model=list[ServiceRead])
async def list_services(db: AsyncSession = Depends(get_db)) -> list[Service]:
    result = await db.execute(select(Service).order_by(Service.id))
    return list(result.scalars().all())


@app.get("/services/{service_id}", response_model=ServiceRead)
async def get_service(service_id: int, db: AsyncSession = Depends(get_db)) -> Service:
    return await _get_or_404(Service, service_id, db)


@app.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: int, db: AsyncSession = Depends(get_db)) -> None:
    svc = await _get_or_404(Service, service_id, db)
    await db.delete(svc)
    await db.commit()


# ------------------------------ Bookmarks ------------------------------


@app.post("/bookmarks", response_model=BookmarkRead, status_code=status.HTTP_201_CREATED)
async def create_bookmark(payload: BookmarkCreate, db: AsyncSession = Depends(get_db)) -> Bookmark:
    bm = Bookmark(**payload.model_dump())
    db.add(bm)
    await db.commit()
    await db.refresh(bm)
    return bm


@app.get("/bookmarks", response_model=list[BookmarkRead])
async def list_bookmarks(db: AsyncSession = Depends(get_db)) -> list[Bookmark]:
    result = await db.execute(select(Bookmark).order_by(Bookmark.id))
    return list(result.scalars().all())


@app.get("/bookmarks/{bookmark_id}", response_model=BookmarkRead)
async def get_bookmark(bookmark_id: int, db: AsyncSession = Depends(get_db)) -> Bookmark:
    return await _get_or_404(Bookmark, bookmark_id, db)


@app.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(bookmark_id: int, db: AsyncSession = Depends(get_db)) -> None:
    bm = await _get_or_404(Bookmark, bookmark_id, db)
    await db.delete(bm)
    await db.commit()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)