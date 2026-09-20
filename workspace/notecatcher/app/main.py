from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from app.core.security import SecurityHeadersMiddleware

app = FastAPI(
    title="Notecatcher API",
    description="Ein kleiner FastAPI-Backend-Microservice für Notizen",
    version="1.0.0"
)

app.add_middleware(SecurityHeadersMiddleware)

# In-Memory Speicher für Notizen
_notes: list[dict] = []
_next_id: int = 1

class NoteCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    tag: str | None = Field(default=None, max_length=50)

class Note(NoteCreate):
    id: int

@app.get("/health")
def health_check():
    """Einfacher Health-Endpoint für Smoke-Tests"""
    return {"status": "ok"}

@app.post("/notes", response_model=Note, status_code=201)
def create_note(note: NoteCreate):
    """Lege eine neue Notiz an und gib sie zurück"""
    global _next_id
    new_note = note.model_dump()
    new_note["id"] = _next_id
    _next_id += 1
    _notes.append(new_note)
    return new_note

@app.get("/notes", response_model=list[Note])
def list_notes():
    """Gib alle gespeicherten Notizen zurück"""
    return _notes

@app.get("/notes/{note_id}", response_model=Note)
def get_note(note_id: int):
    """Gib eine einzelne Notiz zurück oder 404, falls nicht gefunden"""
    for note in _notes:
        if note["id"] == note_id:
            return note
    raise HTTPException(status_code=404, detail="Note not found")
