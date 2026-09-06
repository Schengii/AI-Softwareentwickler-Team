import asyncio
import json

from aiokafka import AIOKafkaConsumer


async def consume_webhooks():
    consumer = AIOKafkaConsumer(
        'webhook_events',
        bootstrap_servers='localhost:9092',
        group_id="webhook_processor_group"
    )
    await consumer.start()
    try:
        async for msg in consumer:
            event = json.loads(msg.value.decode('utf-8'))
            # Logik: DB-Update auf 'PROCESSED', ggf. Webhook-Forwarding
            print(f"Processing event: {event}")
    finally:
        await consumer.stop()

if __name__ == "__main__":
    asyncio.run(consume_webhooks())
