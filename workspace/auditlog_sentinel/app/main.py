from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.auth import get_current_user
from app.database import Base, engine
from app.security import setup_security

app = FastAPI(title="AuditLog Sentinel")

# Security Setup
setup_security(app)

# Statische Dateien bereitstellen (Frontend)
# WICHTIG: Damit Module korrekt geladen werden, muss der Server 
# die korrekten MIME-Types für .js/.tsx liefern. 
# FastAPI's StaticFiles macht das automatisch korrekt.
app.mount("/src", StaticFiles(directory="src"), name="src")

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

@app.get("/secure-data")
async def get_secure_data(current_user: str = Depends(get_current_user)):
    return {"message": f"Hello {current_user}, this is secure data."}
