"""Pydantic-Schemas für ToggleForge."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TargetingRuleBase(BaseModel):
    attribute_name: str = Field(..., min_length=1, max_length=100)
    operator: str = Field(..., min_length=1, max_length=50)  # equals, in, not_in, contains
    values: str = Field(..., description="Komma-separierte Werte oder Einzelwert")
    enabled: bool = True
    priority: int = 0


class TargetingRuleCreate(TargetingRuleBase):
    pass


class TargetingRuleOut(TargetingRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    flag_id: int
    created_at: datetime


class FeatureFlagBase(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    flag_type: str = Field(default="boolean", pattern=r"^(boolean|percentage|targeting)$")
    enabled: bool = False
    rollout_percentage: int = Field(default=0, ge=0, le=100)


class FeatureFlagCreate(FeatureFlagBase):
    targeting_rules: list[TargetingRuleCreate] = Field(default_factory=list)


class FeatureFlagUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    flag_type: str | None = Field(default=None, pattern=r"^(boolean|percentage|targeting)$")
    enabled: bool | None = None
    rollout_percentage: int | None = Field(default=None, ge=0, le=100)
    targeting_rules: list[TargetingRuleCreate] | None = None


class FeatureFlagOut(FeatureFlagBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    targeting_rules: list[TargetingRuleOut] = Field(default_factory=list)


class EvaluateRequest(BaseModel):
    flag_key: str
    entity_id: str | None = None
    user_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvaluateResponse(BaseModel):
    flag_key: str
    enabled: bool
    reason: str


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    flag_key: str
    action: str
    actor: str | None = None
    old_state: str | None = None
    new_state: str | None = None
    details: str | None = None
    created_at: datetime
