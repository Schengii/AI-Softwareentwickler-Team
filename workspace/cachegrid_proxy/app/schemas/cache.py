"""Pydantic-Schemas für Cache-Operationen und Inspektion."""

from typing import Any

from pydantic import BaseModel, Field


class CacheSetRequest(BaseModel):
    """Payload zum Speichern eines Cache-Eintrags."""

    key: str = Field(..., min_length=1, description="Eindeutiger Cache-Schlüssel")
    value: Any = Field(..., description="Zu speichernder Wert (JSON-kompatibel)")
    ttl: float | None = Field(default=None, ge=0.0, description="Optionale TTL in Sekunden")
    tags: list[str] | None = Field(default=None, description="Optionale Tags zur Gruppierung")
    write_behind: bool | None = Field(default=None, description="Write-Behind Disk-Persistenz überschreiben")


class ReadThroughRequest(BaseModel):
    """Payload zur Simulation eines Read-Through Abrufs mit Thundering-Herd-Schutz."""

    key: str = Field(..., min_length=1, description="Cache-Schlüssel")
    mock_upstream_value: Any = Field(default=None, description="Wert, der bei Cache-Miss berechnet wird")
    simulate_delay_seconds: float = Field(default=0.05, ge=0.0, le=10.0, description="Simulierte Upstream-Latenz")
    ttl: float | None = Field(default=None, ge=0.0, description="TTL für das neu geladene Element")
    tags: list[str] | None = Field(default=None, description="Tags für das neu geladene Element")


class CacheItemResponse(BaseModel):
    """Antwortmodell für ausgelesene Cache-Einträge."""

    key: str
    value: Any
    tier: str | None = None
    ttl_remaining_seconds: float | None = None
    tags: list[str] = []


class TagInvalidateRequest(BaseModel):
    """Anfrage zur selektiven Invalidierung via Tags."""

    tags: list[str] = Field(..., min_length=1, description="Liste der Tags")
    mode: str = Field(default="any", pattern="^(any|all)$", description="'any' (Oder-Verknüpfung) oder 'all' (Und-Verknüpfung)")


class TagInvalidateResponse(BaseModel):
    """Antwort nach Tag-Invalidierung."""

    invalidated_keys: list[str]
    count: int
    tags_affected: list[str]


class KeyInspectResponse(BaseModel):
    """Detaillierte Metadaten eines Cache-Eintrags."""

    key: str
    value: Any
    tier: str
    created_at: float
    expires_at: float | None = None
    ttl_remaining_seconds: float | None = None
    access_count: int
    last_accessed_at: float
    tags: list[str]
    is_expired: bool


class CacheStatsResponse(BaseModel):
    """Umfassende Statistik über alle Tiers und Locking-Mechanismen."""

    status: str
    overall_hit_rate_percent: float
    read_through_requests: int
    thundering_herd_prevention_hits: int
    active_concurrency_locks: int
    tags_count: int
    memory_tier: dict[str, Any]
    disk_tier: dict[str, Any]
    write_behind: dict[str, Any]
