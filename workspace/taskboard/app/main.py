from fastapi import FastAPI

from app.core.security import setup_security

app = FastAPI(title="Kanban Tool API")

# Security Setup
setup_security(app)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
