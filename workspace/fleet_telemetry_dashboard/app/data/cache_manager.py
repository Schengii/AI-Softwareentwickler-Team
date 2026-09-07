import json

import redis

from app.core.config import settings


class CacheManager:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

    def get_vehicle_telemetry(self, vehicle_id: str) -> dict | None:
        data = self.redis.get(f"vehicle:{vehicle_id}:latest")
        return json.loads(data) if data else None

cache_manager = CacheManager()
