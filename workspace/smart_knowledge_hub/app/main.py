import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from app.core.config import get_settings
from app.core.vault import VaultManager
from app.core.graph import GraphBuilder
from app.core.adr import ADRGenerator


# Pydantic Schemas für API-Requests und Responses
class NoteCreateUpdateRequest(BaseModel):
    path: str = Field(..., description="Relativer Dateipfad der Notiz, z.B. 'notes/test.md'")
    content: str = Field(..., description="Markdown-Inhalt der Notiz")
    frontmatter: Optional[Dict[str, Any]] = Field(default=None, description="Optionale Frontmatter-Metadaten")


class SearchQueryRequest(BaseModel):
    query: str = Field(..., description="Suchbegriff oder Frage für Semantik-/BM25-Suche")
    top_k: int = Field(default=5, description="Anzahl der maximalen Suchtreffer")


class ADRGenerateRequest(BaseModel):
    title: str = Field(..., description="Titel des Architecture Decision Records")
    context: str = Field(..., description="Kontext und Problembeschreibung")
    decision: str = Field(..., description="Die getroffene Entscheidung")
    consequences: str = Field(..., description="Konsequenzen und Trade-offs")
    status: Optional[str] = Field(default="Angenommen", description="Status des ADRs")


# Services initialisieren
settings = get_settings()
vault_service = VaultService(vault_dir=settings.VAULT_DIR)
graph_service = KnowledgeGraphService(vault_service=vault_service)
adr_generator = ADRGenerator(vault_service=vault_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan-Handler für Startup und Graceful Shutdown."""
    # Vault-Verzeichnis bei Bedarf anlegen / prüfen
    os.makedirs(settings.VAULT_DIR, exist_ok=True)
    yield
    # Shutdown-Bereinigung falls nötig


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware konfigurieren
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    """Health-Check-Endpunkt für Monitoring und Readiness-Checks."""
    return {"status": "ok"}


# --- Vault API Endpoints ---
@app.get(f"{settings.API_V1_PREFIX}/vault/tree", tags=["Vault"])
async def get_vault_tree() -> Dict[str, Any]:
    """Gibt die Dateibaum-Hierarchie des Vaults zurück."""
    try:
        tree = vault_service.get_tree()
        return {"tree": tree}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(f"{settings.API_V1_PREFIX}/vault/note", tags=["Vault"])
async def get_note(path: str = Query(..., description="Relativer Pfad der Notiz")) -> Dict[str, Any]:
    """Liest eine spezifische Notiz inklusive geparster Metadaten und Inhalt."""
    try:
        note = vault_service.get_note(path)
        if not note:
            raise HTTPException(status_code=404, detail="Notiz nicht gefunden")
        return {"note": note}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.API_V1_PREFIX}/vault/note", status_code=status.HTTP_201_CREATED, tags=["Vault"])
async def save_note(request: NoteCreateUpdateRequest) -> Dict[str, Any]:
    """Erstellt oder überschreibt eine Notiz im Vault."""
    try:
        result = vault_service.save_note(path=request.path, content=request.content, frontmatter=request.frontmatter)
        return {"status": "saved", "path": request.path, "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(f"{settings.API_V1_PREFIX}/vault/note", tags=["Vault"])
async def delete_note(path: str = Query(..., description="Relativer Pfad der zu löschenden Notiz")) -> Dict[str, Any]:
    """Löscht eine Notiz aus dem Vault."""
    try:
        success = vault_service.delete_note(path)
        if not success:
            raise HTTPException(status_code=404, detail="Notiz existiert nicht")
        return {"status": "deleted", "path": path}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Graph API Endpoints ---
@app.get(f"{settings.API_V1_PREFIX}/graph", tags=["Graph"])
async def get_knowledge_graph() -> Dict[str, Any]:
    """Gibt den Wissensgraphen (Knoten und Kanten/Wikilinks) zurück."""
    try:
        graph_data = graph_service.build_graph()
        return {"graph": graph_data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- Search API Endpoints ---
@app.post(f"{settings.API_V1_PREFIX}/search", tags=["Search"])
async def search_vault(request: SearchQueryRequest) -> Dict[str, Any]:
    """Durchsucht den Vault mit Volltext/BM25-Suche."""
    try:
        results = vault_service.search(query=request.query, top_k=request.top_k)
        return {"query": request.query, "results": results}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- ADR Generator API Endpoints ---
@app.post(f"{settings.API_V1_PREFIX}/adr/generate", status_code=status.HTTP_201_CREATED, tags=["ADR"])
async def generate_adr(request: ADRGenerateRequest) -> Dict[str, Any]:
    """Generiert ein standardisiertes Architecture Decision Record im Vault."""
    try:
        adr_data = adr_generator.generate(
            title=request.title,
            context=request.context,
            decision=request.decision,
            consequences=request.consequences,
            status=request.status or "Angenommen"
        )
        return {"status": "created", "adr": adr_data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Statische Dateien mounten, falls das static-Verzeichnis existiert
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 8000)),
        reload=settings.DEBUG,
    )
