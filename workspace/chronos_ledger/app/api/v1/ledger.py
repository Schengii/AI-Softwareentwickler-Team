"""Ledger API v1 Endpunkte."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.services.ledger_service import ledger_service
from app.services.ring_buffer import ring_buffer

router = APIRouter(prefix="/api/v1/ledger", tags=["Ledger"])


class LedgerIngestRequest(BaseModel):
    tenant_id: str = Field(..., description="Eindeutige Mandanten-ID")
    payload: dict[str, Any] = Field(..., description="Audit-Log Nutzdaten")


class LedgerVerifyResponse(BaseModel):
    tenant_id: str
    is_valid: bool
    corrupted_index: int | None = None
    total_entries: int


@router.post("/entries", status_code=status.HTTP_202_ACCEPTED)
async def ingest_entry(
    request: LedgerIngestRequest,
    _authorized: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Nimmt Audit-Events asynchron über den In-Memory Ring-Buffer entgegen."""
    queued = await ring_buffer.put({
        "tenant_id": request.tenant_id,
        "payload": request.payload,
    })
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Buffer overflow: Ring-Puffer ausgelastet",
        )
    return {"status": "queued", "tenant_id": request.tenant_id}


@router.post("/entries/sync", status_code=status.HTTP_201_CREATED)
async def ingest_entry_sync(
    request: LedgerIngestRequest,
    _authorized: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Synchrones Ingestieren und direkte Hash-Generierung."""
    entry = ledger_service.append(tenant_id=request.tenant_id, payload=request.payload)
    return {"status": "created", "entry": entry}


@router.get("/entries/{tenant_id}")
async def get_entries(
    tenant_id: str,
    _authorized: bool = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """Gibt alle Ledger-Einträge eines Mandanten zurück."""
    return ledger_service.get_chain(tenant_id)


@router.get("/verify/{tenant_id}", response_model=LedgerVerifyResponse)
async def verify_chain(
    tenant_id: str,
    _authorized: bool = Depends(verify_api_key),
) -> LedgerVerifyResponse:
    """Verifiziert die kryptografische SHA-256 Hash-Kette eines Mandanten."""
    is_valid, corrupted_idx = ledger_service.verify_chain(tenant_id)
    chain = ledger_service.get_chain(tenant_id)
    return LedgerVerifyResponse(
        tenant_id=tenant_id,
        is_valid=is_valid,
        corrupted_index=corrupted_idx,
        total_entries=len(chain),
    )
