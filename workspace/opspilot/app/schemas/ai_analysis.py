from typing import Any

from pydantic import BaseModel, Field


class IncidentPayload(BaseModel):
    incident_id: str
    service_name: str
    error_code: str
    message: str
    metadata: dict[str, Any] | None = None

class WorkflowRecommendation(BaseModel):
    incident_id: str
    severity: str
    analysis: str
    suggested_workflow: dict[str, Any] = Field(..., description="Action, confidence and reasoning")
