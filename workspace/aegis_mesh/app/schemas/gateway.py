# app/schemas/gateway.py

from pydantic import BaseModel, ConfigDict, Field


class RequestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., description="Angefragter Endpunkt")
    method: str = Field(..., pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    client_ip: str = Field(..., description="Client IP-Adresse")
    headers_count: int = Field(default=0, ge=0)
    payload_size: int = Field(default=0, ge=0)

class ScoringResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    risk_score: float = Field(..., ge=0.0, le=1.0, description="ML-berechneter Risikoscore")
    is_anomaly: bool = Field(..., description="Erkennung als anomaler Traffic")
    applied_limit: int = Field(..., description="Dynamisch reduziertes Limit")

class RateLimitStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    client_id: str
    allowed: bool
    remaining_tokens: int = Field(..., ge=0)
    reset_in_seconds: int = Field(..., ge=0)
    risk_score: float | None = Field(default=0.0, nullable=True)
