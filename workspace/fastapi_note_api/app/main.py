# app/main.py
import logging
from fastapi import FastAPI, Depends, HTTPException, status
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, init_db
from app.models import Note
from app.schemas import NoteCreate, NoteRead

# Logger konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# -------------------------------------------------------------------------
# Startup‑Hook: Datenbanktabellen erzeugen
# -------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Initialisiere Datenbank...")
    await init_db()
    logger.info("Datenbank bereit.")

# -------------------------------------------------------------------------
# Endpunkt: Notiz anlegen
# -------------------------------------------------------------------------
@app.post(
    "/notes/",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    note: NoteCreate,
    session: AsyncSession = Depends(get_session),
):
    db_note = Note.from_orm(note)
    session.add(db_note)
    try:
        await session.commit()
        await session.refresh(db_note)
        logger.info("Notiz erstellt: id=%s", db_note.id)
        return db_note
    except Exception as exc:
        await session.rollback()
        logger.error("Fehler beim Erstellen einer Notiz: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create note",
        )

# -------------------------------------------------------------------------
# Endpunkt: Notizen listen
# -------------------------------------------------------------------------
@app.get(
    "/notes/",
    response_model=list[NoteRead],
    status_code=status.HTTP_200_OK,
)
async def list_notes(session: AsyncSession = Depends(get_session)):
    result = await session.exec(select(Note))
    notes = result.all()
    logger.info("Liste von %d Notizen abgerufen.", len(notes))
    return notes

# -------------------------------------------------------------------------
# Endpunkt: Notiz löschen
# -------------------------------------------------------------------------
@app.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_note(
    note_id: int,
    session: AsyncSession = Depends(get_session),
):
    note = await session.get(Note, note_id)
    if not note:
        logger.warning("Löschversuch für nicht vorhandene Notiz id=%s", note_id)
        raise HTTPException(status_code=404, detail="Note not found")
    await session.delete(note)
    await session.commit()
    logger.info("Notiz gelöscht: id=%s", note_id)
    return None
