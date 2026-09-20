from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime

from app.db.session import get_db
from app.db.models import WorkflowDefinition, WorkflowInstance, AuditLogEntry
from app.schemas.workflows import (
    WorkflowDefinitionCreate, WorkflowDefinitionResponse,
    WorkflowInstanceCreate, WorkflowInstanceResponse,
    TransitionRequest, AuditLogEntryResponse
)
from app.engine.state_machine import StateMachineEngine, StateMachineError
from app.engine.hash_chain import HashChainService

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

@router.post("/definitions", response_model=WorkflowDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_definition(definition: WorkflowDefinitionCreate, db: AsyncSession = Depends(get_db)):
    db_def = WorkflowDefinition(
        name=definition.name,
        initial_state=definition.initial_state,
        states=definition.states,
        transitions=definition.transitions
    )
    db.add(db_def)
    await db.commit()
    await db.refresh(db_def)
    return db_def

@router.post("/instances", response_model=WorkflowInstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_instance(instance: WorkflowInstanceCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkflowDefinition).filter(WorkflowDefinition.id == instance.definition_id))
    definition = result.scalars().first()
    if not definition:
        raise HTTPException(status_code=404, detail="Workflow definition not found")

    db_instance = WorkflowInstance(
        definition_id=definition.id,
        current_state=definition.initial_state,
        data=instance.data
    )
    db.add(db_instance)
    await db.flush()

    timestamp = datetime.utcnow()
    payload_hash = HashChainService.compute_payload_hash(instance.data)
    prev_hash = HashChainService.GENESIS_HASH
    current_hash = HashChainService.compute_entry_hash(
        timestamp=timestamp,
        actor_id=instance.actor_id,
        action="CREATE",
        payload_hash=payload_hash,
        prev_hash=prev_hash
    )

    audit_entry = AuditLogEntry(
        instance_id=db_instance.id,
        sequence_number=1,
        from_state=None,
        to_state=definition.initial_state,
        action="CREATE",
        actor_id=instance.actor_id,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        current_hash=current_hash,
        timestamp=timestamp
    )
    db.add(audit_entry)
    await db.commit()
    await db.refresh(db_instance)
    return db_instance

@router.post("/instances/{instance_id}/transitions", response_model=WorkflowInstanceResponse)
async def execute_transition(instance_id: str, transition: TransitionRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkflowInstance).filter(WorkflowInstance.id == instance_id))
    instance = result.scalars().first()
    if not instance:
        raise HTTPException(status_code=404, detail="Workflow instance not found")

    result_def = await db.execute(select(WorkflowDefinition).filter(WorkflowDefinition.id == instance.definition_id))
    definition = result_def.scalars().first()

    try:
        next_state = StateMachineEngine.validate_transition(
            definition=definition,
            current_state=instance.current_state,
            action=transition.action,
            payload=transition.payload
        )
    except StateMachineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get last audit entry for prev_hash
    result_audit = await db.execute(
        select(AuditLogEntry)
        .filter(AuditLogEntry.instance_id == instance_id)
        .order_by(AuditLogEntry.sequence_number.desc())
        .limit(1)
    )
    last_audit = result_audit.scalars().first()
    
    prev_hash = last_audit.current_hash if last_audit else HashChainService.GENESIS_HASH
    seq_num = (last_audit.sequence_number + 1) if last_audit else 1

    timestamp = datetime.utcnow()
    payload_hash = HashChainService.compute_payload_hash(transition.payload)
    current_hash = HashChainService.compute_entry_hash(
        timestamp=timestamp,
        actor_id=transition.actor_id,
        action=transition.action,
        payload_hash=payload_hash,
        prev_hash=prev_hash
    )

    audit_entry = AuditLogEntry(
        instance_id=instance.id,
        sequence_number=seq_num,
        from_state=instance.current_state,
        to_state=next_state,
        action=transition.action,
        actor_id=transition.actor_id,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        current_hash=current_hash,
        timestamp=timestamp
    )
    db.add(audit_entry)

    instance.current_state = next_state
    if transition.payload:
        if not instance.data:
            instance.data = {}
        instance.data.update(transition.payload)
    instance.version += 1
    
    await db.commit()
    await db.refresh(instance)
    return instance

@router.get("/instances/{instance_id}/audit", response_model=List[AuditLogEntryResponse])
async def get_audit_log(instance_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AuditLogEntry)
        .filter(AuditLogEntry.instance_id == instance_id)
        .order_by(AuditLogEntry.sequence_number.asc())
    )
    return result.scalars().all()
