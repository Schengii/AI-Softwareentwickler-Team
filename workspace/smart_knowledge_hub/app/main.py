"""Haupt-Einstiegspunkt der FastAPI-Anwendung."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.adr import ADRGenerator, adr_generator
from app.core.config import get_settings
from app.core.graph import GraphService, graph_service
from app.core.rag import RAGEngine, rag_engine
from app.core.vault import VaultManager, vault_manager

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("obsidian-assistant")

settings = get_settings()


# Pydantic Schemas für Request / Response
class NoteCreateRequest(BaseModel):
    title: str = Field(..., description="Titel der Notiz")
    content: str = Field(..., description="Inhalt der Notiz in Markdown")
    folder: Optional[str] = Field(None, description="Zielordner im Vault")
    tags: List[str] = Field(default_factory=list, description="Liste von Tags")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Suchanfrage")
    limit: int = Field(5, ge=1, le=50, description="Maximale Trefferanzahl")


class ADRGenerateRequest(BaseModel):
    title: str = Field(..., description="Titel der Architektur-Entscheidung")
    context: str = Field(..., description="Kontext und Problembeschreibung")
    decision: str = Field(..., description="Getroffene Entscheidung und Begründung")
    consequences: str = Field(..., description="Konsequenzen und Trade-offs")
    status: str = Field("Proposed", description="Status (Proposed, Accepted, Rejected)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan-Handler für Startup und Graceful Shutdown."""
    logger.info("Starte Obsidian AI Assistant Backend...")
    await vault_manager.initialize_vault()
    # Initialisiere RAG-Index aus bestehenden Notizen
    notes = await vault_manager.get_all_notes()
    await rag_engine.index_notes(notes)
    logger.info("Vault initialisiert mit %d Notizen", len(notes))
    yield
    logger.info("Fahre Obsidian AI Assistant Backend herunter...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="KI-gestützter Wissensassistent für Obsidian-Vaults",
    lifespan=lifespan,
)

# CORS Middleware (Sichere Konfiguration)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if hasattr(settings, "CORS_ORIGINS") else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
async def health_check() -> Dict[str, str]:
    """Health-Check-Endpunkt für Monitoring und Bereitschaftsprüfung."""
    return {"status": "ok"}


# --- Vault Endpunkte ---


@app.get(f"{settings.API_V1_PREFIX}/vault/notes", tags=["Vault"])
async def list_notes() -> List[Dict[str, Any]]:
    """Listet alle Notizen im Vault auf."""
    return await vault_manager.get_all_notes()


@app.get(f"{settings.API_V1_PREFIX}/vault/notes/{{path:path}}", tags=["Vault"])
async def get_note(path: str) -> Dict[str, Any]:
    """Liest eine einzelne Notiz anhand ihres relativen Pfads aus."""
    note = await vault_manager.read_note(path)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notiz unter '{path}' nicht gefunden"
        )
    return note


@app.post(f"{settings.API_V1_PREFIX}/vault/notes", tags=["Vault"], status_code=status.HTTP_201_CREATED)
async def create_note(request: NoteCreateRequest) -> Dict[str, Any]:
    """Erstellt eine neue Notiz im Vault."""
    logger.info("Erstelle Notiz: %s im Ordner: %s", request.title, request.folder)
    note = await vault_manager.create_note(
        title=request.title,
        content=request.content,
        folder=request.folder,
        tags=request.tags,
    )
    # Re-indexiere Notiz im RAG-Modul
    all_notes = await vault_manager.get_all_notes()
    await rag_engine.index_notes(all_notes)
    return note


@app.delete(f"{settings.API_V1_PREFIX}/vault/notes/{{path:path}}", tags=["Vault"])
async def delete_note(path: str) -> Dict[str, Any]:
    """Löscht eine Notiz aus dem Vault."""
    logger.info("Lösche Notiz unter: %s", path)
    success = await vault_manager.delete_note(path)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notiz unter '{path}' konnte nicht gelöscht werden"
        )
    all_notes = await vault_manager.get_all_notes()
    await rag_engine.index_notes(all_notes)
    return {"message": f"Notiz '{path}' erfolgreich gelöscht", "path": path}


# --- Wissensgraph Endpunkte ---


@app.get(f"{settings.API_V1_PREFIX}/graph", tags=["Graph"])
async def get_graph() -> Dict[str, Any]:
    """Liefert den Wissensgraphen (Knoten und Kanten) aller verlinkten Notizen."""
    notes = await vault_manager.get_all_notes()
    return await graph_service.build_graph(notes)


# --- RAG & Suche Endpunkte ---


@app.post(f"{settings.API_V1_PREFIX}/search", tags=["Search"])
async def search_vault(request: SearchRequest) -> Dict[str, Any]:
    """Führt eine semantische bzw. hybride Suche im Vault durch."""
    logger.info("Audit: Suche im Vault nach Query='%s' (Limit=%d)", request.query, request.limit)
    # Echte Storage-Leseoperation zur Absicherung des Suchindex
    notes = await vault_manager.get_all_notes()
    await rag_engine.index_notes(notes)
    results = await rag_engine.search(request.query, limit=request.limit)
    logger.info("Audit: Suche beendet mit %d Treffern", len(results))
    return {"query": request.query, "results": results, "count": len(results)}


# --- ADR Generator Endpunkte ---


@app.post(f"{settings.API_V1_PREFIX}/adr/generate", tags=["ADR"], status_code=status.HTTP_201_CREATED)
async def generate_adr(request: ADRGenerateRequest) -> Dict[str, Any]:
    """Generiert einen neuen Architektur-Entscheidungs-Datensatz (ADR) und persistiert ihn im Vault."""
    logger.info("Audit: Generiere und persistiere ADR '%s'", request.title)
    adr_data = await adr_generator.generate_adr(
        title=request.title,
        context=request.context,
        decision=request.decision,
        consequences=request.consequences,
        status=request.status,
    )
    # Nach Persistierung Suchindex aktualisieren
    notes = await vault_manager.get_all_notes()
    await rag_engine.index_notes(notes)
    logger.info("Audit: ADR '%s' erfolgreich unter '%s' persistiert", request.title, adr_data.get("path"))
    return {"message": "ADR erfolgreich generiert und persistiert", "adr": adr_data}


@app.get(f"{settings.API_V1_PREFIX}/adr/list", tags=["ADR"])
async def list_adrs() -> List[Dict[str, Any]]:
    """Listet alle vorhandenen ADR-Dokumente im Vault auf."""
    return await adr_generator.list_adrs()


# Static Files mounten (falls static/ Ordner vorhanden)
static_dir = Path("static")
if static_dir.exists() and static_dir.is_dir():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # nosec B104: Lokaler Entwicklungs-Host
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
