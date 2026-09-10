import asyncio
from typing import Optional

from src.events.schemas import BaseEvent


class EventBroker:
    _instance: Optional['EventBroker'] = None
    
    def __init__(self):
        self.queue = asyncio.Queue()
        
    @classmethod
    def get_instance(cls) -> 'EventBroker':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def enqueue(self, event: BaseEvent):
        await self.queue.put(event)

async def event_consumer():
    broker = EventBroker.get_instance()
    while True:
        event = await broker.queue.get()
        # Hier erfolgt die eigentliche Verarbeitung (z.B. DB-Write)
        # Für das MVP reicht ein Logging
        print(f"Processing event: {event.event_type} at {event.timestamp}")
        broker.queue.task_done()
