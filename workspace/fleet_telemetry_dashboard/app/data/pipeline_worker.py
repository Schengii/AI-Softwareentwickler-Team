import json
import logging

import redis
from kafka import KafkaConsumer

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelemetryConsumer:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.consumer = KafkaConsumer(
            'telemetry_topic',
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id='telemetry_group',
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )

    def run(self):
        logger.info("Starting Kafka consumer...")
        for message in self.consumer:
            data = message.value
            vehicle_id = data.get("vehicle_id")
            if vehicle_id:
                # Update Hot Cache (Redis)
                self.redis.setex(f"vehicle:{vehicle_id}:latest", 300, json.dumps(data))
                logger.debug(f"Updated cache for vehicle {vehicle_id}")

if __name__ == "__main__":
    consumer = TelemetryConsumer()
    consumer.run()
