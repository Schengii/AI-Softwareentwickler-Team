"""REST-API Endpunkte für ToggleForge."""

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import AuditLog, FeatureFlag, TargetingRule, get_db
from app.schemas import (
    AuditLogOut,
    EvaluateRequest,
    EvaluateResponse,
    FeatureFlagCreate,
    FeatureFlagOut,
    FeatureFlagUpdate,
)
from app.services.evaluator import evaluate_flag

router = APIRouter()


@router.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health-Endpoint für Liveness- und Readiness-Probes."""
    return {"status": "ok"}


@router.get("/flags", response_model=list[FeatureFlagOut], tags=["Flags"])
async def list_flags(db: AsyncSession = Depends(get_db)) -> list[FeatureFlag]:
    """Liefert alle konfigurierten Feature-Flags inkl. Targeting-Regeln."""
    stmt = (
        select(FeatureFlag)
        .options(selectinload(FeatureFlag.targeting_rules))
        .order_by(FeatureFlag.key.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/flags", response_model=FeatureFlagOut, status_code=status.HTTP_201_CREATED, tags=["Flags"])
async def create_flag(
    flag_in: FeatureFlagCreate,
    db: AsyncSession = Depends(get_db),
) -> FeatureFlag:
    """Erstellt ein neues Feature-Flag und protokolliert die Aktion im Audit-Log."""
    stmt = select(FeatureFlag).where(FeatureFlag.key == flag_in.key)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"FeatureFlag mit Key '{flag_in.key}' existiert bereits.",
        )

    flag = FeatureFlag(
        key=flag_in.key,
        name=flag_in.name,
        description=flag_in.description,
        flag_type=flag_in.flag_type,
        enabled=flag_in.enabled,
        rollout_percentage=flag_in.rollout_percentage,
    )
    db.add(flag)
    await db.flush()

    for rule_in in flag_in.targeting_rules:
        rule = TargetingRule(
            flag_id=flag.id,
            attribute_name=rule_in.attribute_name,
            operator=rule_in.operator,
            values=rule_in.values,
            enabled=rule_in.enabled,
            priority=rule_in.priority,
        )
        db.add(rule)

    audit = AuditLog(
        flag_key=flag.key,
        action="create",
        actor="system",
        new_state=json.dumps({"enabled": flag.enabled, "type": flag.flag_type}),
        details=f"Flag '{flag.name}' angelegt.",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(flag)
    # Eager reload for response
    stmt = select(FeatureFlag).where(FeatureFlag.id == flag.id).options(selectinload(FeatureFlag.targeting_rules))
    res = await db.execute(stmt)
    return res.scalar_one()


@router.get("/flags/{key}", response_model=FeatureFlagOut, tags=["Flags"])
async def get_flag(key: str, db: AsyncSession = Depends(get_db)) -> FeatureFlag:
    """Gibt Details eines bestimmten Feature-Flags zurück."""
    stmt = select(FeatureFlag).where(FeatureFlag.key == key).options(selectinload(FeatureFlag.targeting_rules))
    res = await db.execute(stmt)
    flag = res.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Flag '{key}' nicht gefunden.")
    return flag


@router.put("/flags/{key}", response_model=FeatureFlagOut, tags=["Flags"])
async def update_flag(
    key: str,
    flag_update: FeatureFlagUpdate,
    db: AsyncSession = Depends(get_db),
) -> FeatureFlag:
    """Aktualisiert ein bestehendes Feature-Flag und protokolliert die Änderungen."""
    stmt = select(FeatureFlag).where(FeatureFlag.key == key).options(selectinload(FeatureFlag.targeting_rules))
    res = await db.execute(stmt)
    flag = res.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Flag '{key}' nicht gefunden.")

    old_state = {"enabled": flag.enabled, "rollout_percentage": flag.rollout_percentage}

    if flag_update.name is not None:
        flag.name = flag_update.name
    if flag_update.description is not None:
        flag.description = flag_update.description
    if flag_update.flag_type is not None:
        flag.flag_type = flag_update.flag_type
    if flag_update.enabled is not None:
        flag.enabled = flag_update.enabled
    if flag_update.rollout_percentage is not None:
        flag.rollout_percentage = flag_update.rollout_percentage

    if flag_update.targeting_rules is not None:
        flag.targeting_rules.clear()
        for rule_in in flag_update.targeting_rules:
            rule = TargetingRule(
                flag_id=flag.id,
                attribute_name=rule_in.attribute_name,
                operator=rule_in.operator,
                values=rule_in.values,
                enabled=rule_in.enabled,
                priority=rule_in.priority,
            )
            flag.targeting_rules.append(rule)

    new_state = {"enabled": flag.enabled, "rollout_percentage": flag.rollout_percentage}
    audit = AuditLog(
        flag_key=flag.key,
        action="update",
        actor="system",
        old_state=json.dumps(old_state),
        new_state=json.dumps(new_state),
        details="Flag aktualisiert.",
    )
    db.add(audit)
    await db.commit()
    await db.refresh(flag)
    return flag


@router.delete("/flags/{key}", status_code=status.HTTP_204_NO_CONTENT, tags=["Flags"])
async def delete_flag(key: str, db: AsyncSession = Depends(get_db)) -> None:
    """Löscht ein Feature-Flag und vermerkt das Löschen im Audit-Log."""
    stmt = select(FeatureFlag).where(FeatureFlag.key == key)
    res = await db.execute(stmt)
    flag = res.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Flag '{key}' nicht gefunden.")

    audit = AuditLog(
        flag_key=flag.key,
        action="delete",
        actor="system",
        details=f"Flag '{key}' gelöscht.",
    )
    db.add(audit)
    await db.delete(flag)
    await db.commit()


@router.post("/evaluate", response_model=EvaluateResponse, tags=["Evaluation"])
async def evaluate(
    payload: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> EvaluateResponse:
    """Evaluiert den Zustand eines Flags für eine gegebene Entity oder User."""
    stmt = select(FeatureFlag).where(FeatureFlag.key == payload.flag_key).options(selectinload(FeatureFlag.targeting_rules))
    res = await db.execute(stmt)
    flag = res.scalar_one_or_none()

    entity_id = payload.entity_id or payload.user_id or "anonymous"
    result = evaluate_flag(flag, entity_id=entity_id, attributes=payload.attributes)
    return result


@router.get("/audit", response_model=list[AuditLogOut], tags=["Audit"])
async def get_audit_logs(
    flag_key: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    """Gibt die lückenlose Historie aller Flag-Modifikationen zurück."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if flag_key:
        stmt = stmt.where(AuditLog.flag_key == flag_key)
    res = await db.execute(stmt)
    return list(res.scalars().all())
