# Integration in main.py (Finaler Schritt)
from fastapi.middleware.cors import CORSMiddleware
from auth import oauth2_scheme

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Validierung via jose.jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return {"username": "authenticated_user"}
