"""Pydantic-Schemas für Datenvalidierung und API-Contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class ItemPayload(BaseModel):
    title: str
    description: str | None = None


class ItemCreate(ItemPayload):
    pass


class ItemUpdate(ItemPayload):
    pass


class Item(ItemPayload):
    id: int
    owner_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
