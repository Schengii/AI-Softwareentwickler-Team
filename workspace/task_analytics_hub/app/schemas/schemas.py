from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: Optional[str] = "pending"


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class TaskResponse(TaskBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TeamMetricBase(BaseModel):
    metric_name: str
    value: float
    notes: Optional[str] = None


class TeamMetricCreate(TeamMetricBase):
    pass


class TeamMetricUpdate(BaseModel):
    metric_name: Optional[str] = None
    value: Optional[float] = None
    notes: Optional[str] = None


class TeamMetricResponse(TeamMetricBase):
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
