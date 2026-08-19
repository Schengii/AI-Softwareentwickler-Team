# app/main.py
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, users, jobs, applications, admin
from app.db.base import create_db_and_tables

app = FastAPI(
    title="Jobsuche – API",
    description="AI‑gestützte Jobplattform – Must‑Have MVP",
    version="1.0.0",
)

# CORS (für Frontend‑Entwicklung)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router registrieren
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["User"])
app.include_router(jobs.router, prefix="/jobs", tags=["Job"])
app.include_router(applications.router, prefix="/applications", tags=["Application"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])

# Datenbank‑Tabellen beim Start erzeugen (SQLite‑Demo)
@app.on_event("startup")
async def on_startup():
    await create_db_and_tables()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
