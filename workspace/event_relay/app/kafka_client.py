import json
import os

from aiokafka import AIOKafkaProducer

from app.resilience import resilience

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

class KafkaProducerManager:
    def __init__(self):
        self.producer = None

    async def start(self):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await self.producer.start()

    @resilience.retry_with_backoff()
    @resilience.circuit_breaker
    async def send_event(self, topic: str, event_data: dict):
        await self.producer.send_and_wait(topic, event_data)

    async def stop(self):
        await self.producer.stop()
