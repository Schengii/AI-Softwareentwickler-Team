import asyncio
import logging


async def run_polling():
    while True:
        logging.info("Polling services...")
        await asyncio.sleep(60)
