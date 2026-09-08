from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import create_access_token, get_password_hash, verify_password

router = APIRouter()

# Mock-Datenbank für MVP
users_db = {
    "admin": get_password_hash("admin")
}

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    hashed_pw = users_db.get(form_data.username)
    if not hashed_pw or not verify_password(form_data.password, hashed_pw):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    
    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}

