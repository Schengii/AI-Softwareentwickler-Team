from datetime import datetime, timedelta

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

from src.auth.security import get_current_user, require_role
from src.config import get_settings

settings = get_settings()

app = FastAPI(title="LogiPulse API")

# CORS Konfiguration: Dynamisch aus Config
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Dummy-Validierung für den Proof-of-Concept
    if form_data.username != "admin" or form_data.password != "secret":
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token_expires = timedelta(minutes=30)
    payload = {
        "sub": form_data.username,
        "role": "admin",
        "exp": datetime.utcnow() + access_token_expires
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/v1/protected")
async def protected_route(user: dict = Depends(get_current_user)):
    return {"message": "Hello user", "user": user}

@app.get("/api/v1/admin")
async def admin_route(user: dict = Depends(require_role("admin"))):
    return {"message": "Hello admin", "user": user}
