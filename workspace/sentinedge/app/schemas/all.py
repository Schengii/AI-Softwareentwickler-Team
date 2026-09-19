from datetime import datetime

from pydantic import BaseModel, Field


class SecretCreate(BaseModel):
    key: str
    value: str
    ttl_seconds: int | None = None

class SecretResponse(BaseModel):
    id: int
    key: str
    version: int
    ttl_expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

class SecretValueResponse(BaseModel):
    key: str
    value: str
    version: int

class FeatureFlagCreate(BaseModel):
    key: str
    is_enabled: bool = False
    rollout_percentage: float = Field(0.0, ge=0.0, le=100.0)

class FeatureFlagResponse(BaseModel):
    id: int
    key: str
    is_enabled: bool
    rollout_percentage: float
    created_at: datetime

    model_config = {"from_attributes": True}

class ApiKeyCreate(BaseModel):
    name: str
    scopes: str

class ApiKeyResponse(BaseModel):
    id: int
    name: str
    scopes: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

class ApiKeyCreateResponse(ApiKeyResponse):
    raw_key: str # Only returned once on creation
