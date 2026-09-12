"""API-Endpunkte des HookSentinel Webhook-Gateways.

Deckt gemäß specs/openapi.yaml ab:
- POST /webhook/{source_slug}: Webhook-Ingestion mit HMAC-Prüfung & Idempotenz
- GET  /dlq: Dead-Letter-Queue auflisten
- POST /dlq/{event_id}/replay: DLQ-Event manuell erneut zur Zustellung einreihen
- GET  /events: Übersicht der zuletzt empfangenen Webhook-Events
- GET  /stats: Aggregierte Kennzahlen zum Gateway-Zustand
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import DeadLetterEntry, EventStatus, Source, WebhookEvent, get_db
from app.services.security import verify_hmac_signature

router = APIRouter()


def _extract_signature(request: Request) -> str | None:
    """Liest die HMAC-Signatur aus dem Standard- oder GitHub-kompatiblen Header."""
    return request.headers.get("X-Signature") or request.headers.get("X-Hub-Signature-256")


@router.post("/webhook/{source_slug}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_webhook(
    source_slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Nimmt eine Webhook-Payload entgegen, prüft HMAC-Signatur und Idempotenz
    und reiht das Event zur asynchronen Auslieferung ein."""
    result = await db.execute(select(Source).where(Source.slug == source_slug))
    source = result.scalar_one_or_none()
    if source is None or not source.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_source", "message": f"Unbekannte oder inaktive Quelle: {source_slug}"},
        )

    raw_body = await request.body()

    if source.secret:
        signature = _extract_signature(request)
        if not signature or not verify_hmac_signature(raw_body, signature, source.secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_signature", "message": "HMAC-SHA256 signature verification failed"},
            )

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_payload", "message": "Payload ist kein gültiges JSON"},
        ) from exc

    idempotency_key = request.headers.get("X-Idempotency-Key")
    if idempotency_key:
        existing = await db.execute(
            select(WebhookEvent).where(WebhookEvent.idempotency_key == idempotency_key)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "idempotency_conflict", "message": "Webhook wurde bereits verarbeitet"},
            )

    event = WebhookEvent(
        source_id=source.id,
        idempotency_key=idempotency_key,
        event_type=payload.get("event_type") if isinstance(payload, dict) else None,
        payload=payload,
        headers=dict(request.headers),
        status=EventStatus.PENDING,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    return {
        "status": "accepted",
        "event_id": event.id,
        "source_slug": source_slug,
        "idempotency_key": idempotency_key,
    }


@router.get("/dlq")
async def list_dlq_events(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Liefert alle Einträge der Dead-Letter-Queue."""
    result = await db.execute(
        select(DeadLetterEntry, WebhookEvent, Source)
        .join(WebhookEvent, DeadLetterEntry.event_id == WebhookEvent.id)
        .join(Source, WebhookEvent.source_id == Source.id)
        .order_by(DeadLetterEntry.created_at.desc())
    )
    return [
        {
            "id": dlq_entry.id,
            "source_slug": source.slug,
            "failure_reason": dlq_entry.reason,
            "retry_count": event.retry_count,
            "created_at": dlq_entry.created_at.isoformat(),
        }
        for dlq_entry, event, source in result.all()
    ]


@router.post("/dlq/{event_id}/replay")
async def replay_dlq_event(event_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Setzt ein DLQ-Event manuell auf PENDING zurück, damit der Relay-Dispatcher
    es erneut zuzustellen versucht."""
    result = await db.execute(
        select(DeadLetterEntry).where(DeadLetterEntry.event_id == event_id)
    )
    dlq_entry = result.scalar_one_or_none()
    if dlq_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Kein DLQ-Eintrag für Event {event_id}"},
        )

    event_result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"Event {event_id} existiert nicht mehr"},
        )

    event.status = EventStatus.PENDING
    event.retry_count = 0
    event.next_retry_at = None
    dlq_entry.replay_count += 1

    await db.delete(dlq_entry)
    await db.commit()

    return {"replayed": True, "event_id": event_id, "new_status": EventStatus.PENDING.value}


@router.get("/events")
async def list_events(limit: int = 50, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Liefert die zuletzt empfangenen Webhook-Events zur Übersicht/Diagnose."""
    result = await db.execute(
        select(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": event.id,
            "source_id": event.source_id,
            "event_type": event.event_type,
            "status": event.status.value,
            "retry_count": event.retry_count,
            "created_at": event.created_at.isoformat(),
        }
        for event in result.scalars().all()
    ]


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Liefert aggregierte Kennzahlen zum aktuellen Zustand des Gateways."""
    result = await db.execute(
        select(WebhookEvent.status, func.count()).group_by(WebhookEvent.status)
    )
    status_counts = {row[0].value: row[1] for row in result.all()}

    dlq_result = await db.execute(select(func.count()).select_from(DeadLetterEntry))
    dlq_count = dlq_result.scalar_one()

    source_result = await db.execute(select(func.count()).select_from(Source))
    source_count = source_result.scalar_one()

    return {
        "events_by_status": status_counts,
        "dlq_count": dlq_count,
        "source_count": source_count,
    }
