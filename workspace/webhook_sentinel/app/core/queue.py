import asyncio
from typing import Any, Dict
from uuid import UUID

class WebhookTask:
    def __init__(self, subscription_id: UUID, event_id: str, payload: Dict[str, Any], secret: str, target_url: str):
        self.subscription_id = subscription_id
        self.event_id = event_id
        self.payload = payload
        self.secret = secret
        self.target_url = target_url

# Global Queue
webhook_queue: asyncio.Queue[WebhookTask] = asyncio.Queue()
