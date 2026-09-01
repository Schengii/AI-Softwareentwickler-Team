from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta
import uuid

app = FastAPI(title="CloudVault API")

# --- Pydantic Modelle ---

class FileMetadata(BaseModel):
    id: uuid.UUID
    filename: str
    tags: List[str] = []
    created_at: datetime

class ShareRequest(BaseModel):
    expires_in_hours: int = Field(default=24, gt=0)

class ShareResponse(BaseModel):
    token: str
    download_url: str
    expires_at: datetime

# --- Endpunkte ---

@app.post("/api/v1/files/upload", response_model=FileMetadata)
async def upload_file(file: UploadFile = File(...), tags: Optional[str] = None):
    """
    Lädt eine Datei hoch, verschlüsselt sie (simuliert) und speichert Metadaten.
    """
    # Hier würde die AES-256-GCM Verschlüsselung und S3-Speicherung erfolgen
    file_id = uuid.uuid4()
    return FileMetadata(
        id=file_id,
        filename=file.filename,
        tags=tags.split(",") if tags else [],
        created_at=datetime.utcnow()
    )

@app.get("/api/v1/files", response_model=List[FileMetadata])
async def list_files():
    """
    Listet alle Dateien des authentifizierten Benutzers auf.
    """
    return []

@app.post("/api/v1/files/{file_id}/link", response_model=ShareResponse)
async def create_share_link(file_id: uuid.UUID, request: ShareRequest):
    """
    Erstellt einen temporären Download-Link.
    """
    token = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(hours=request.expires_in_hours)
    return ShareResponse(
        token=token,
        download_url=f"/api/v1/download/{token}",
        expires_at=expires_at
    )

@app.get("/api/v1/tags", response_model=List[str])
async def get_tags():
    """
    Gibt alle verfügbaren Tags zurück.
    """
    return ["work", "private", "important"]
