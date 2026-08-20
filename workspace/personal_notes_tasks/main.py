from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4

app = FastAPI(title="Task & Note API")

# --- Modelle ---
class Note(BaseModel):
    id: str = None
    title: str
    content: str

class Task(BaseModel):
    id: str = None
    title: str
    completed: bool = False

# --- In-Memory Speicher ---
notes = []
tasks = []

# --- Endpunkte Notizen ---
@app.post("/notes/", response_model=Note)
def create_note(note: Note):
    note.id = str(uuid4())
    notes.append(note)
    return note

@app.get("/notes/", response_model=List[Note])
def get_notes():
    return notes

@app.delete("/notes/{note_id}")
def delete_note(note_id: str):
    global notes
    notes = [n for n in notes if n.id != note_id]
    return {"message": "Note deleted"}

# --- Endpunkte Aufgaben ---
@app.post("/tasks/", response_model=Task)
def create_task(task: Task):
    task.id = str(uuid4())
    tasks.append(task)
    return task

@app.get("/tasks/", response_model=List[Task])
def get_tasks():
    return tasks

@app.put("/tasks/{task_id}/complete")
def complete_task(task_id: str):
    for task in tasks:
        if task.id == task_id:
            task.completed = True
            return task
    raise HTTPException(status_code=404, detail="Task not found")
