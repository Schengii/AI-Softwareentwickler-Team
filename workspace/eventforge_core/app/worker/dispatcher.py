import hashlib
import hmac
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeliveryLog, Endpoint

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackoffConfig(BaseModel):
    initial_interval_seconds: float = Field(default=1.0, ge=0.1)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_interval_seconds: float = Field(default=60.0, ge=1.0)
    max_retries: int = Field(default=5, ge=0)
    jitter: bool = Field(default=True)
    request_timeout_seconds: float = Field(default=10.0, ge=0.5)

    def calculate_backoff(self, attempt_count: int) -> float:
        delay = self.initial_interval_seconds * (self.backoff_multiplier ** max(0, attempt_count - 1))
        delay = min(delay, self.max_interval_seconds)
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return max(0.1, delay)


class DeliveryResult(BaseModel):
    success: bool
    status_code: int | None = None
    error_message: str | None = None
    attempt_count: int
    is_dead_letter: bool = False
    next_retry_at: datetime | None = None


class WebhookDispatcher:
    def __init__(
        self,
        config: BackoffConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.config = config or BackoffConfig()
        self._http_client = http_client
        self._dlq_events: list[dict[str, Any]] = []

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            return httpx.AsyncClient(timeout=self.config.request_timeout_seconds)
        return self._http_client

    @staticmethod
    def compute_signature(secret: str, payload_bytes: bytes) -> str:
        return hmac.new(
            key=secret.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()

    async def deliver(
        self,
        target_url: str,
        payload: Any,
        secret: str | None = None,
        custom_headers: dict[str, str] | None = None,
    ) -> tuple[bool, int | None, str | None]:
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = str(payload).encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "EventForge-Core/1.0",
        }
        if custom_headers:
            headers.update(custom_headers)

        if secret:
            signature = self.compute_signature(secret, body)
            headers["X-Signature-SHA256"] = signature
            headers["X-Hub-Signature-256"] = f"sha256={signature}"

        client = await self._get_client()
        should_close_client = self._http_client is None

        try:
            response = await client.post(
                url=target_url,
                content=body,
                headers=headers,
                timeout=self.config.request_timeout_seconds,
            )
            success = 200 <= response.status_code < 300
            err_msg = None if success else f"HTTP error {response.status_code}: {response.text[:200]}"
            return success, response.status_code, err_msg
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError) as exc:
            return False, None, f"{type(exc).__name__}: {exc!s}"
        except Exception as exc:  # noqa: BLE001 - Dispatcher fängt alle Netzwerk/Client-Exceptions ab
            return False, None, f"Unexpected delivery error: {exc!s}"
        finally:
            if should_close_client:
                await client.aclose()

    async def process_delivery_attempt(
        self,
        session: AsyncSession,
        delivery_log_id: UUID,
    ) -> DeliveryResult:
        query = select(DeliveryLog).where(DeliveryLog.id == delivery_log_id)
        result = await session.execute(query)
        delivery_log = result.scalar_one_or_none()

        if not delivery_log:
            raise ValueError(f"DeliveryLog with id {delivery_log_id} not found")

        endpoint_query = select(Endpoint).where(Endpoint.id == delivery_log.endpoint_id)
        ep_result = await session.execute(endpoint_query)
        endpoint = ep_result.scalar_one_or_none()

        if not endpoint:
            delivery_log.status = "dead_letter"
            delivery_log.error_message = "Associated endpoint does not exist or was deleted"
            delivery_log.updated_at = utcnow()
            await session.commit()
            return DeliveryResult(
                success=False,
                status_code=None,
                error_message=delivery_log.error_message,
                attempt_count=delivery_log.attempt_count,
                is_dead_letter=True,
            )

        if not endpoint.is_active:
            delivery_log.status = "dead_letter"
            delivery_log.error_message = "Endpoint is inactive"
            delivery_log.updated_at = utcnow()
            await session.commit()
            return DeliveryResult(
                success=False,
                status_code=None,
                error_message=delivery_log.error_message,
                attempt_count=delivery_log.attempt_count,
                is_dead_letter=True,
            )

        delivery_log.attempt_count += 1
        now = utcnow()

        success, status_code, error_message = await self.deliver(
            target_url=endpoint.url,
            payload=delivery_log.payload,
            secret=endpoint.secret,
        )

        delivery_log.status_code = status_code
        delivery_log.error_message = error_message
        delivery_log.updated_at = now

        if success:
            delivery_log.status = "success"
            delivery_log.next_retry_at = None
            await session.commit()
            return DeliveryResult(
                success=True,
                status_code=status_code,
                error_message=None,
                attempt_count=delivery_log.attempt_count,
                is_dead_letter=False,
            )

        # Retry logic & Dead-Letter Queue
        if delivery_log.attempt_count >= self.config.max_retries:
            delivery_log.status = "dead_letter"
            delivery_log.next_retry_at = None
            await session.commit()
            self._record_dlq_event(delivery_log, endpoint)
            return DeliveryResult(
                success=False,
                status_code=status_code,
                error_message=error_message,
                attempt_count=delivery_log.attempt_count,
                is_dead_letter=True,
            )

        backoff_seconds = self.config.calculate_backoff(delivery_log.attempt_count)
        delivery_log.status = "failed"
        delivery_log.next_retry_at = now + timedelta(seconds=backoff_seconds)
        await session.commit()

        return DeliveryResult(
            success=False,
            status_code=status_code,
            error_message=error_message,
            attempt_count=delivery_log.attempt_count,
            is_dead_letter=False,
            next_retry_at=delivery_log.next_retry_at,
        )

    def _record_dlq_event(self, delivery_log: DeliveryLog, endpoint: Endpoint) -> None:
        event = {
            "delivery_log_id": str(delivery_log.id),
            "endpoint_id": str(endpoint.id),
            "url": endpoint.url,
            "attempt_count": delivery_log.attempt_count,
            "error_message": delivery_log.error_message,
            "status_code": delivery_log.status_code,
            "payload": delivery_log.payload,
            "moved_to_dlq_at": utcnow().isoformat(),
        }
        self._dlq_events.append(event)
        logger.warning("Event moved to Dead-Letter-Queue: %s", event)

    def get_dlq_events(self) -> list[dict[str, Any]]:
        return list(self._dlq_events)
