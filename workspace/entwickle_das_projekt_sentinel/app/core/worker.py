import asyncio
from datetime import datetime, timezone

from app.api.websocket import manager
from app.core.buffer import telemetry_buffer
from app.core.detector import detector
from app.db.models import Telemetry
from app.db.session import AsyncSessionLocal


async def process_buffer():
    while True:
        items = telemetry_buffer.pop_all()
        if items:
            async with AsyncSessionLocal() as session:
                for item in items:
                    is_anomaly, z_score = detector.process(item["device_id"], item["metric"], item["value"])
                    
                    db_item = Telemetry(
                        device_id=item["device_id"],
                        metric=item["metric"],
                        value=item["value"],
                        timestamp=item.get("timestamp") or datetime.now(timezone.utc),
                        is_anomaly=is_anomaly,
                        z_score=z_score
                    )
                    session.add(db_item)
                    
                    # Broadcast
                    await manager.broadcast({
                        "device_id": item["device_id"],
                        "metric": item["metric"],
                        "value": item["value"],
                        "is_anomaly": is_anomaly,
                        "z_score": z_score
                    })
                
                await session.commit()
                
        await asyncio.sleep(1.0)
