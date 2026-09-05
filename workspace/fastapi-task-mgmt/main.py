# Integration in main.py (Finaler Schritt)
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
import schemas
from auth import oauth2_scheme

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Validierung via jose.jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return {"username": "authenticated_user"}


# Platzhalter-Nutzer, solange kein echter Registrierungs-/Login-Flow verdrahtet ist:
# schemas.TaskCreate kennt bewusst kein user_id-Feld (der Aufrufer soll das nicht selbst
# setzen können) - ohne einen echten Auth-Flow gibt es aber noch keine Quelle für die
# tatsächliche Nutzer-ID. models.Task.user_id ist als reine Fremdschlüssel-Spalte (kein
# ForeignKeyConstraint mit ON DELETE/erzwungener Prüfung) definiert, SQLite prüft
# Fremdschlüssel zudem standardmäßig nicht (PRAGMA foreign_keys ist hier nicht aktiviert) -
# ein noch nicht existierender Nutzer 1 bricht die Einfüge-Operation deshalb nicht ab.
_PLACEHOLDER_USER_ID = 1


@app.post("/tasks/", response_model=schemas.Task)
async def create_task(task: schemas.TaskCreate, db: AsyncSession = Depends(models.get_db)):
    db_task = models.Task(title=task.title, status=task.status, user_id=_PLACEHOLDER_USER_ID)
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.get("/tasks/", response_model=list[schemas.Task])
async def read_tasks(db: AsyncSession = Depends(models.get_db)):
    result = await db.execute(select(models.Task))
    return result.scalars().all()
