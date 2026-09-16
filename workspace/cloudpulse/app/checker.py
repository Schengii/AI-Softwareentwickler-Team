import asyncio
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.db.base import async_session
from app.db.models import Monitor


class BackgroundChecker:
    def __init__(self):
        self.is_running = False
        self.task = None
        self.client = None

    async def start(self):
        self.is_running = True
        self.client = httpx.AsyncClient()
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.aclose()

    async def _run_loop(self):
        while self.is_running:
            try:
                await self._check_all()
            except Exception as e:
                print(f"Error in background checker loop: {e}")
            await asyncio.sleep(10)

    async def _check_all(self):
        async with async_session() as db:
            result = await db.execute(select(Monitor))
            monitors = result.scalars().all()
            
            now = datetime.now(timezone.utc)
            tasks = []
            
            for monitor in monitors:
                if monitor.last_checked:
                    last_checked = monitor.last_checked
                    if last_checked.tzinfo is None:
                        last_checked = last_checked.replace(tzinfo=timezone.utc)
                    
                    elapsed = (now - last_checked).total_seconds()
                    if elapsed < monitor.interval_seconds:
                        continue
                
                tasks.append(self._check_monitor(db, monitor))
            
            if tasks:
                await asyncio.gather(*tasks)

    async def _check_monitor(self, db, monitor: Monitor):
        start_time = time.monotonic()
        try:
            response = await self.client.get(monitor.url, timeout=monitor.timeout)
            latency_ms = (time.monotonic() - start_time) * 1000
            
            monitor.last_checked = datetime.now(timezone.utc)
            monitor.last_status_code = response.status_code
            monitor.last_latency_ms = latency_ms
            monitor.is_up = (response.status_code == monitor.expected_status)
            monitor.last_error = None
            
        except Exception as e:
            monitor.last_checked = datetime.now(timezone.utc)
            monitor.last_status_code = None
            monitor.last_latency_ms = None
            monitor.is_up = False
            monitor.last_error = str(e)
            
        db.add(monitor)
        await db.commit()

checker = BackgroundChecker()
