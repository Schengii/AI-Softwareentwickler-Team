from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class CircuitState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"

class DispatchRequest(BaseModel):
    service: str
    target: str
    path: str
    method: str
    payload: Optional[Dict[str, Any]] = None

class DispatchResponse(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    
class HealthResponse(BaseModel):
    status: str
