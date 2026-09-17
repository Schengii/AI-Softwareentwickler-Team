import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saga import Saga, SagaStep

logger = logging.getLogger(__name__)

class SagaOrchestrator:
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def execute_workflow(self, saga_id: str, ws_manager=None):
        result = await self.session.execute(select(Saga).where(Saga.id == saga_id))
        saga = result.scalar_one_or_none()
        if not saga:
            return
            
        saga.status = "RUNNING"
        await self.session.commit()
        if ws_manager:
            await ws_manager.broadcast({"id": saga.id, "status": saga.status})
            
        steps_to_run = ["validate_order", "process_payment", "update_inventory"]
        executed_steps = []
        
        try:
            for step_name in steps_to_run:
                step = SagaStep(saga_id=saga.id, step_name=step_name, status="PENDING")
                self.session.add(step)
                await self.session.commit()
                
                await asyncio.sleep(0.5)
                
                if step_name == "process_payment" and saga.payload and saga.payload.get("fail"):
                    raise Exception("Payment failed")
                    
                step.status = "SUCCESS"
                step.result = {"msg": f"{step_name} completed"}
                await self.session.commit()
                executed_steps.append(step)
                
                if ws_manager:
                    await ws_manager.broadcast({"id": saga.id, "status": f"RUNNING ({step_name})"})
                    
            saga.status = "COMPLETED"
            await self.session.commit()
            if ws_manager:
                await ws_manager.broadcast({"id": saga.id, "status": saga.status})
                
        except Exception as e:
            logger.error(f"Saga {saga_id} failed at {step_name}: {e}")
            step.status = "FAILED"
            step.error = str(e)
            saga.status = "FAILED"
            await self.session.commit()
            
            if ws_manager:
                await ws_manager.broadcast({"id": saga.id, "status": "COMPENSATING"})
                
            for exec_step in reversed(executed_steps):
                await asyncio.sleep(0.2)
                exec_step.status = "COMPENSATED"
                await self.session.commit()
                
            saga.status = "COMPENSATED"
            await self.session.commit()
            if ws_manager:
                await ws_manager.broadcast({"id": saga.id, "status": saga.status})
