from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- Step Schemas ---

class StepDefinition(BaseModel):
    id: str | None = None
    name: str
    type: str = Field(description="Typ des Steps: 'shell', 'http', 'transform'")
    command: str | None = None
    url: str | None = None
    method: str | None = "GET"
    transform_op: str | None = None
    input_data: Any | None = None

    model_config = ConfigDict(extra="allow")

# --- Pipeline Schemas ---

class PipelineBase(BaseModel):
    name: str
    description: str | None = None
    trigger_type: str = Field(default="MANUAL", description="MANUAL oder SCHEDULE")
    steps: list[StepDefinition] = Field(default_factory=list)

class PipelineCreate(PipelineBase):
    pass

class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    steps: list[StepDefinition] | None = None

class StepExecutionResponse(BaseModel):
    id: int
    run_id: int
    step_id: str
    name: str
    type: str
    order_index: int
    status: str
    logs: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None

    model_config = ConfigDict(from_attributes=True)

class PipelineRunResponse(BaseModel):
    id: int
    pipeline_id: int
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    step_executions: list[StepExecutionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

class PipelineResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    trigger_type: str
    steps: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    last_run_status: str | None = None

    model_config = ConfigDict(from_attributes=True)

class StatsResponse(BaseModel):
    total_pipelines: int
    total_runs: int
    total_tasks: int
    successful_runs: int
    failed_runs: int
    cancelled_runs: int
    success_rate: float
    average_duration_seconds: float

    model_config = ConfigDict(from_attributes=True)
