# Integration in main.py (Finaler Schritt)
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
import schemas
from auth import create_access_token, get_current_user, get_password_hash, verify_password

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
async def register(user: schemas.UserCreate, db: AsyncSession = Depends(models.get_db)):
    existing = await db.execute(select(models.User).where(models.User.username == user.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Benutzername bereits vergeben.")
    db_user = models.User(username=user.username, hashed_password=get_password_hash(user.password))
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


# tokenUrl="token" (siehe auth.oauth2_scheme) legt den Pfad dieses Endpunkts fest - ein Client,
# der nur die OpenAPI-Doku kennt, findet den Login-Endpunkt darüber automatisch (z.B. Swagger
# UIs "Authorize"-Dialog). OAuth2PasswordRequestForm erwartet klassische Login-Formular-Felder
# (username/password, application/x-www-form-urlencoded) statt JSON - Standard-Konvention des
# OAuth2-"Password"-Flows, den FastAPI hier abbildet.
@app.post("/token", response_model=schemas.Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(models.get_db)):
    result = await db.execute(select(models.User).where(models.User.username == form_data.username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falscher Benutzername oder falsches Passwort.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token({"sub": user.username})
    return schemas.Token(access_token=access_token)


@app.post("/tasks/", response_model=schemas.Task)
async def create_task(
    task: schemas.TaskCreate,
    db: AsyncSession = Depends(models.get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_task = models.Task(title=task.title, status=task.status, user_id=current_user.id)
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task


@app.get("/tasks/", response_model=list[schemas.Task])
async def read_tasks(
    db: AsyncSession = Depends(models.get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Auf den angemeldeten Nutzer skoped (kein "jeder sieht alle Tasks") - jetzt, wo ein echter
    # Auth-Flow existiert, ist das die naheliegende Erwartung an eine Aufgabenverwaltung.
    result = await db.execute(select(models.Task).where(models.Task.user_id == current_user.id))
    return result.scalars().all()
