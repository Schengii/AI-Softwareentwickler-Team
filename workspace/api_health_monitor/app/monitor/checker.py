import asyncio, httpx, uuid, time
from app.schemas import AlertEvent, StatusEvent
from app.database import SessionLocal, CheckHistory

class HealthMonitor:
    def __init__(self):
        self.checks = {} # {id: {url, interval, ...}}
        self.subscribers = set()

    def add_check(self, check):
        check_id = str(uuid.uuid4())
        data = check.model_dump() if hasattr(check, "model_dump") else check.dict()
        data['id'] = check_id
        self.checks[check_id] = data
        return data

    async def run(self):
        while True:
            for check in list(self.checks.values()):
                await self.check_url(check)
            await asyncio.sleep(10)

    async def check_url(self, check):
        latency = 0.0
        status_code = 0
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                start = time.perf_counter()
                response = await client.get(check["url"])
                latency = (time.perf_counter() - start) * 1000
                status_code = response.status_code
            status = "up" if response.status_code < 400 else "down"
        except httpx.HTTPError:
            status = "down"

        # Persist to DB
        db = SessionLocal()
        try:
            history = CheckHistory(check_id=check["id"], latency=latency, status_code=status_code)
            db.add(history)
            db.commit()
        finally:
            db.close()

        if status == "down":
            await self.notify_alert(check["id"], f"{check['url']} ist nicht erreichbar")
        await self._broadcast(StatusEvent(check_id=check["id"], status=status))

    async def notify_alert(self, check_id, message):
        await self._broadcast(AlertEvent(check_id=check_id, message=message))

    async def _broadcast(self, event):
        payload = event.model_dump_json()
        for subscriber in list(self.subscribers):
            try:
                await subscriber.send_text(payload)
            except Exception:
                self.subscribers.discard(subscriber)


monitor = HealthMonitor()
