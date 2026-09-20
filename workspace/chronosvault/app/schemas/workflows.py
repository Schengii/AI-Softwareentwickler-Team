from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional, List
from datetime import datetime

class WorkflowDefinitionCreate(BaseModel):
    name: str
    initial_state: str
    states: List[str]
    transitions: List[Dict[str, Any]]

class WorkflowDefinitionResponse(WorkflowDefinitionCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)

class WorkflowInstanceCreate(BaseModel):
    definition_id: str
    data: Optional[Dict[str, Any]] = None
    actor_id: str

class WorkflowInstanceResponse(BaseModel):
    id: str
    definition_id: str
    current_state: str
    data: Optional[Dict[str, Any]] = None
    version: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class TransitionRequest(BaseModel):
    action: str
    actor_id: str
    payload: Optional[Dict[str, Any]] = None

class AuditLogEntryResponse(BaseModel):
    id: str
    instance_id: str
    sequence_number: int
    from_state: Optional[str] = None
    to_state: str
    action: str
    actor_id: str
    payload_hash: str
    prev_hash: str
    current_hash: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)
