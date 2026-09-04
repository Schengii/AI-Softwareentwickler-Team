# app/schemas.py
from datetime import datetime

from pydantic import BaseModel, EmailStr, condecimal, constr


class UserCreate(BaseModel):
    username: constr(min_length=3, max_length=50, regex=r'^[a-zA-Z0-9_]+$')
    email: EmailStr
    password: constr(min_length=8, max_length=128)

class UserRead(BaseModel):
    id: int
    username: str
    email: EmailStr
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True

class ProjectCreate(BaseModel):
    name: constr(min_length=1, max_length=100)
    description: str | None = None
    hourly_rate: condecimal(gt=0, max_digits=10, decimal_places=2) | None = None

# weitere Schemas analog …
