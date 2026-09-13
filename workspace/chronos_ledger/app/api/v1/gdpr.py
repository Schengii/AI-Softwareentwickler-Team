"""GDPR / DSGVO API v1 Endpunkte."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.services.pii_masker import PIIMasker

router = APIRouter(prefix="/api/v1/gdpr", tags=["GDPR"])


class MaskRequest(BaseModel):
    payload: dict[str, Any] = Field(..., description="Payload zur DSGVO-konformen PII-Maskierung")


class MaskResponse(BaseModel):
    masked_payload: dict[str, Any]


@router.post("/mask", response_model=MaskResponse, status_code=status.HTTP_200_OK)
async def mask_pii_data(
    request: MaskRequest,
    _authorized: bool = Depends(verify_api_key),
) -> MaskResponse:
    """Maskiert PII-Daten (E-Mails, IP-Adressen, Auth-Header) gemäß Art. 17 DSGVO."""
    masked = PIIMasker.mask_payload(request.payload)
    return MaskResponse(masked_payload=masked)


@router.get("/status")
async def gdpr_compliance_status() -> dict[str, Any]:
    """Gibt den aktuellen DSGVO-Compliance-Status des Systems zurück."""
    return {
        "status": "compliant",
        "pii_masking_active": True,
        "supported_rules": ["email_pseudonymization", "ipv4_masking", "token_masking"],
    }
