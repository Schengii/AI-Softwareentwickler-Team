"""FastAPI Backend-Einstiegspunkt für feature_pilot."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .auth import create_access_token, get_current_user, hash_password, verify_password
from .database import Base, engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tabellen initialisieren
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Feature Pilot API",
    version="1.0.0",
    description="API für Feature-Pilot: Ideen- & Feature-Management-Plattform.",
    lifespan=lifespan,
)

# CORS Middleware für Frontend-Anbindung
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Annotated

# API v1 Router
api_v1 = APIRouter(prefix="/api/v1")


@app.get("/health", tags=["Monitoring"])
def health_check():
    """Health-Check Endpunkt für Container und Smoke-Tests."""
    return {"status": "ok"}


# ── Auth Endpunkte ────────────────────────────────────────────────────────────

@api_v1.post("/auth/login", response_model=schemas.Token, tags=["Auth"])
def login(
    username: Annotated[str, Form(...)],
    password: Annotated[str, Form(...)],
    db: Annotated[Session, Depends(get_db)],
):
    user = crud.get_user_by_email(db, username)
    if not user:
        # Automatischer Demo-/First-Login-User
        user = models.User(
            email=username,
            hashed_password=hash_password(password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Anmeldedaten.",
        )

    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer"}


@api_v1.get("/users/me", response_model=schemas.User, tags=["Users"])
def get_me(current_user: Annotated[models.User, Depends(get_current_user)]):
    return current_user


# ── Items / Features CRUD Endpunkte ────────────────────────────────────────────

@api_v1.get("/items", response_model=list[schemas.Item], tags=["Items"])
def list_items(
    db: Annotated[Session, Depends(get_db)],
    skip: int = 0,
    limit: int = 100,
):
    return crud.get_items(db, skip=skip, limit=limit)


@api_v1.post("/items", response_model=schemas.Item, status_code=status.HTTP_201_CREATED, tags=["Items"])
def create_item(
    item_in: schemas.ItemCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return crud.create_item(db, item_in, owner_id=current_user.id)


@api_v1.get("/items/{item_id}", response_model=schemas.Item, tags=["Items"])
def get_item(
    item_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    item = crud.get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item nicht gefunden.")
    return item


@api_v1.put("/items/{item_id}", response_model=schemas.Item, tags=["Items"])
def update_item(
    item_id: int,
    item_in: schemas.ItemUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    item = crud.update_item(db, item_id, item_in)
    if not item:
        raise HTTPException(status_code=404, detail="Item nicht gefunden.")
    return item


@api_v1.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Items"])
def delete_item(
    item_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    deleted = crud.delete_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item nicht gefunden.")


app.include_router(api_v1)
