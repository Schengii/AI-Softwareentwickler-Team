from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SagaCreate(BaseModel):
    workflow_type: str
    payload: dict[str, Any]

class SagaStepOut(BaseModel):
    id: str
    step_name: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class SagaOut(BaseModel):
    id: str
    workflow_type: str
    status: str
    payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime | None = None
    steps: list[SagaStepOut] = []
    
    model_config = ConfigDict(from_attributes=True)
