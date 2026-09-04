from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    id: int
    username: str
    email: EmailStr
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    hourly_rate: Decimal | None = None


class ProjectRead(BaseModel):
    id: int
    name: str
    description: str | None = None
    hourly_rate: Decimal | None = None
    owner_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TimeEntryCreate(BaseModel):
    project_id: int
    start_time: datetime
    end_time: datetime | None = None
    description: str | None = None


class TimeEntryRead(BaseModel):
    id: int
    project_id: int
    user_id: int
    start_time: datetime
    end_time: datetime | None = None
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
