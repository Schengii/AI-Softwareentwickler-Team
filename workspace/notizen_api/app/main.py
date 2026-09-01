from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import uuid

app = FastAPI()

class Note(BaseModel):
    id: str
    title: str
    content: str

class NoteCreate(BaseModel):
    title: str
    content: str

notes_db = {}

@app.post("/notes/", response_model=Note)
def create_note(note: NoteCreate):
    note_id = str(uuid.uuid4())
    new_note = Note(id=note_id, **note.model_dump())
    notes_db[note_id] = new_note
    return new_note

@app.get("/notes/", response_model=List[Note])
def list_notes():
    return list(notes_db.values())

@app.put("/notes/{note_id}", response_model=Note)
def update_note(note_id: str, note_update: NoteCreate):
    if note_id not in notes_db:
        raise HTTPException(status_code=404, detail="Note not found")
    updated_note = Note(id=note_id, **note_update.model_dump())
    notes_db[note_id] = updated_note
    return updated_note

@app.delete("/notes/{note_id}")
def delete_note(note_id: str):
    if note_id not in notes_db:
        raise HTTPException(status_code=404, detail="Note not found")
    del notes_db[note_id]
    return {"message": "Note deleted"}
