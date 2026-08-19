# app/schemas/user.py
from typing import Optional, List
from pydantic import BaseModel, EmailStr, validator

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

    @validator("password")
    def pwd_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")
        return v

class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool
    is_admin: bool

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ProfileUpdate(BaseModel):
    location: Optional[str] = None
    desired_salary: Optional[int] = None
    skills: Optional[List[str]] = None   # CSV‑Konvertierung im Service
