import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_maker
from app.models.webhook import Delivery, Subscription

logger = logging.getLogger(__name__)


def is_ssrf_safe_url(url: str) -> bool:
    """Validates that a URL does not point to internal/private/loopback/link-local IP addresses."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False

        # Disallow localhost directly
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False

        # Resolve hostname to IP addresses
        addr_info = socket.getaddrinfo(hostname, None)
        for entry in addr_info:
            ip_str = entry[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False
        return True
    except Exception as exc:  # noqa: BLE001 - DNS failure or invalid URL format treated as unsafe
        logger.warning("SSRF validation failed for %s: %s", url, exc)
        return False


def generate_hmac_signature(secret: str, payload_bytes: bytes) -> str:
    """Generates an HMAC-SHA256 signature formatted as sha256=<hex_digest>."""
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


class WebhookDispatcher:
    """Async Webhook Dispatcher with background queue and exponential backoff retry."""

    def __init__(self, max_retries: int = 3, base_backoff: float = 0.5):
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self._stop_event = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Starts the background delivery worker."""
        self._stop_event.clear()
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Gracefully stops the worker."""
        self._stop_event.set()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def enqueue_delivery(self, delivery_id: uuid.UUID) -> None:
        """Adds a delivery ID to the processing queue."""
        await self.queue.put({"delivery_id": delivery_id})

    async def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Wait for next item with short timeout to allow check on stop_event
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                delivery_id = item.get("delivery_id")
                if delivery_id:
                    await self.process_delivery(delivery_id)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - Worker loop must stay alive
                logger.exception("Unexpected error in webhook delivery worker: %s", exc)

    async def process_delivery(self, delivery_id: uuid.UUID) -> Delivery:
        """Processes a single delivery with exponential backoff retries."""
        async with async_session_maker() as session:
            stmt = select(Delivery).where(Delivery.id == delivery_id)
            res = await session.execute(stmt)
            delivery = res.scalar_one_or_none()
            if not delivery:
                logger.error("Delivery not found: %s", delivery_id)
                return None

            sub_stmt = select(Subscription).where(Subscription.id == delivery.subscription_id)
            sub_res = await session.execute(sub_stmt)
            subscription = sub_res.scalar_one_or_none()
            if not subscription:
                delivery.status_code = 404
                delivery.response_body = "Subscription not found"
                await session.commit()
                return delivery

            target_url = subscription.target_url
            secret = subscription.secret
            payload_data = delivery.payload
            payload_bytes = json.dumps(payload_data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            signature = generate_hmac_signature(secret, payload_bytes)

            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Event-ID": delivery.event_id,
            }

            # Pre-check SSRF
            if not is_ssrf_safe_url(target_url):
                delivery.status_code = 400
                delivery.response_body = "Target URL rejected: SSRF protection triggered"
                delivery.delivered_at = datetime.now(timezone.utc)
                await session.commit()
                return delivery

            attempt = 0
            last_status: Optional[int] = None
            last_body: Optional[str] = None
            success = False

            client = self._client if (self._client and not self._client.is_closed) else httpx.AsyncClient(timeout=10.0)
            should_close_client = client != self._client

            try:
                for attempt in range(1, self.max_retries + 1):
                    delivery.attempt = attempt
                    try:
                        resp = await client.post(target_url, content=payload_bytes, headers=headers)
                        last_status = resp.status_code
                        last_body = resp.text[:1000]

                        # Success on 2xx
                        if 200 <= resp.status_code < 300:
                            success = True
                            break
                        # If 4xx client error (except 429), don't retry, it's non-transient
                        if 400 <= resp.status_code < 500 and resp.status_code != 429:
                            break
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as err:
                        last_status = None
                        last_body = f"Transport error: {str(err)}"

                    if attempt < self.max_retries:
                        backoff = self.base_backoff * (2 ** (attempt - 1))
                        await asyncio.sleep(backoff)
            finally:
                if should_close_client:
                    await client.aclose()

            delivery.status_code = last_status
            delivery.response_body = last_body
            if success or last_status is not None or attempt == self.max_retries:
                delivery.delivered_at = datetime.now(timezone.utc)

            await session.commit()
            await session.refresh(delivery)
            return delivery


# Singleton dispatcher instance
dispatcher = WebhookDispatcher()
