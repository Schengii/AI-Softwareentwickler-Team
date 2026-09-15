import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models import Delivery, Endpoint, Event, utcnow

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 2.0
BACKOFF_FACTOR = 2.0
MAX_BACKOFF_SECONDS = 300.0


def generate_signature(secret: str, timestamp: int, payload_bytes: bytes) -> str:
    """
    Erzeugt eine HMAC-SHA256 Signatur nach Industriestandard (Stripe/GitHub Style).
    Signierter String: f"{timestamp}.".encode() + payload_bytes
    Rückgabe-Format: "t={timestamp},v1={hex_digest}"
    """
    to_sign = f"{timestamp}.".encode() + payload_bytes
    digest = hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(
    secret: str,
    header_value: str,
    payload_bytes: bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verifiziert HMAC-SHA256 Signatur inkl. Timestamp-Replay-Schutz.
    """
    try:
        parts = dict(item.split("=", 1) for item in header_value.split(","))
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (ValueError, KeyError):
        return False

    current_timestamp = int(time.time())
    if abs(current_timestamp - timestamp) > tolerance_seconds:
        return False

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def calculate_backoff_delay(
    attempt_count: int,
    base_seconds: float = BASE_BACKOFF_SECONDS,
    factor: float = BACKOFF_FACTOR,
    max_seconds: float = MAX_BACKOFF_SECONDS,
    add_jitter: bool = True,
) -> float:
    """
    Berechnet die Verzögerung in Sekunden mittels Exponential Backoff und Full Jitter.
    Nutzt secrets.SystemRandom() für kryptografisch sicheren Jitter.
    """
    if attempt_count <= 0:
        return 0.0

    raw_delay = base_seconds * (factor ** (attempt_count - 1))
    capped_delay = min(raw_delay, max_seconds)

    if add_jitter:
        # Full Jitter: gleichmäßige Verteilung zwischen 0 und capped_delay
        # verhindert Thundering Herd Problem bei kaskadierten Retries
        return secrets.SystemRandom().uniform(0.5 * capped_delay, capped_delay)
    return capped_delay


def calculate_next_backoff(
    attempt_count: int,
    base_seconds: float = BASE_BACKOFF_SECONDS,
    factor: float = BACKOFF_FACTOR,
    max_seconds: float = MAX_BACKOFF_SECONDS,
    add_jitter: bool = True,
) -> datetime:
    """Berechnet den nächsten Ausführungszeitpunkt via exponentiellem Backoff mit Jitter."""
    delay = calculate_backoff_delay(
        attempt_count=attempt_count,
        base_seconds=base_seconds,
        factor=factor,
        max_seconds=max_seconds,
        add_jitter=add_jitter,
    )
    return utcnow() + timedelta(seconds=delay)


class EndpointCircuitBreaker:
    """
    In-Memory Circuit Breaker pro Endpoint-URL.
    Zustände: CLOSED (normal), OPEN (blockiert Aufrufe), HALF_OPEN (Probe-Request).
    Nutzt time.monotonic() für Zeitmessungen.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count: int = 0
        self.state: str = "CLOSED"
        self.last_failure_time: float = 0.0

    def can_attempt(self) -> bool:
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_failure_time >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


class WebhookDispatcher:
    """
    Zentraler Dispatcher für Webhook-Auslieferungen mit HMAC-Signatur,
    exponentiellem Retry-Tracking in SQLite und Circuit-Breaker Absicherung.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client
        self._circuit_breakers: dict[str, EndpointCircuitBreaker] = {}

    def _get_circuit_breaker(self, endpoint_url: str) -> EndpointCircuitBreaker:
        if endpoint_url not in self._circuit_breakers:
            self._circuit_breakers[endpoint_url] = EndpointCircuitBreaker()
        return self._circuit_breakers[endpoint_url]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
            timeout = httpx.Timeout(DEFAULT_TIMEOUT_SECONDS, connect=5.0)
            self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def create_deliveries_for_event(self, event_id: str, session: AsyncSession) -> list[str]:
        """
        Erstellt Delivery-Einträge für alle aktiven registrierten Endpunkte.
        """
        stmt = select(Endpoint)
        result = await session.execute(stmt)
        endpoints = result.scalars().all()

        delivery_ids = []
        for ep in endpoints:
            delivery = Delivery(
                event_id=event_id,
                endpoint_id=ep.id,
                status="pending",
                attempt_count=0,
                next_attempt=utcnow(),
            )
            session.add(delivery)
            delivery_ids.append(delivery.id)

        await session.commit()
        return delivery_ids

    async def dispatch_single_delivery(
        self,
        delivery_id: str,
        session: AsyncSession,
    ) -> tuple[bool, int | None, str | None]:
        """
        Führt einen einzelnen Zustellversuch aus, prüft Circuit Breaker,
        signiert die Payload per HMAC und aktualisiert den Status in der Datenbank
        inkl. exponentiellem Backoff bei Fehlschlägen.
        """
        stmt = select(Delivery).where(Delivery.id == delivery_id)
        res = await session.execute(stmt)
        delivery = res.scalar_one_or_none()

        if not delivery:
            return False, None, f"Delivery {delivery_id} not found"

        event = await session.get(Event, delivery.event_id)
        endpoint = await session.get(Endpoint, delivery.endpoint_id)

        if not event or not endpoint:
            delivery.status = "failed"
            delivery.response_body = "Event or Endpoint missing"
            await session.commit()
            return False, None, delivery.response_body

        cb = self._get_circuit_breaker(endpoint.url)
        if not cb.can_attempt():
            # Circuit breaker ist OPEN: Schone Zielsystem & spare lokale Ressourcen
            backoff_dt = calculate_next_backoff(delivery.attempt_count or 1)
            delivery.next_attempt = backoff_dt
            delivery.response_body = "Circuit Breaker OPEN: Delivery deferred"
            await session.commit()
            return False, 503, delivery.response_body

        delivery.attempt_count = (delivery.attempt_count or 0) + 1

        payload_json = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False)
        payload_bytes = payload_json.encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "EventPulse-Gateway/1.0",
            "X-Event-ID": str(event.id),
            "X-Delivery-ID": str(delivery.id),
            "X-Delivery-Attempt": str(delivery.attempt_count),
        }

        current_time = int(time.time())
        if endpoint.secret:
            signature_header = generate_signature(endpoint.secret, current_time, payload_bytes)
            headers["X-Signature"] = signature_header
            headers["X-Signature-Timestamp"] = str(current_time)

        client = await self._get_client()
        success = False
        resp_status: int | None = None
        resp_body: str | None = None

        try:
            response = await client.post(
                endpoint.url,
                content=payload_bytes,
                headers=headers,
            )
            resp_status = response.status_code
            resp_body = response.text[:2000]

            if 200 <= resp_status < 300:
                success = True
                cb.record_success()
                delivery.status = "success"
                delivery.next_attempt = None
            else:
                success = False
                # Server-Fehler (5xx) lösen Circuit-Breaker Zähler aus, 4xx meist Client-Fehler
                if resp_status >= 500:
                    cb.record_failure()
        except httpx.TimeoutException as exc:
            resp_status = 504
            resp_body = f"Gateway Timeout: {exc!s}"[:2000]
            success = False
            cb.record_failure()
        except httpx.HTTPError as exc:
            resp_status = None
            resp_body = f"HTTP Error: {exc!s}"[:2000]
            success = False
            cb.record_failure()
        except Exception as exc:  # noqa: BLE001 - Abfangen unerwarteter Netzwerk-/Systemfehler pro Request
            resp_status = None
            resp_body = f"Unexpected Error: {exc!s}"[:2000]
            success = False
            cb.record_failure()

        delivery.response_status = resp_status
        delivery.response_body = resp_body
        delivery.updated_at = utcnow()

        if not success:
            if delivery.attempt_count >= MAX_ATTEMPTS:
                delivery.status = "failed"
                delivery.next_attempt = None
            else:
                delivery.status = "pending"
                delivery.next_attempt = calculate_next_backoff(delivery.attempt_count)

        await session.commit()
        return success, resp_status, resp_body

    async def dispatch_event(self, event_id: str) -> None:
        """
        Orchestriert das Anlegen und den ersten Dispatch-Versuch aller Deliveries für ein Event.
        """
        async with async_session_maker() as session:
            delivery_ids = await self.create_deliveries_for_event(event_id, session)

        for del_id in delivery_ids:
            async with async_session_maker() as session:
                await self.dispatch_single_delivery(del_id, session)

    async def process_due_retries(self, limit: int = 50) -> int:
        """
        Sucht alle fälligen Deliveries ('pending' und next_attempt <= now)
        und führt für diese den nächsten Retry-Versuch aus.
        Gibt die Anzahl verarbeiteter Deliveries zurück.
        """
        now = utcnow()
        async with async_session_maker() as session:
            stmt = (
                select(Delivery.id)
                .where(Delivery.status == "pending")
                .where(Delivery.next_attempt <= now)
                .limit(limit)
            )
            res = await session.execute(stmt)
            due_ids = res.scalars().all()

        for del_id in due_ids:
            async with async_session_maker() as session:
                await self.dispatch_single_delivery(del_id, session)

        return len(due_ids)


    async def dispatch_event(self, event_id: str) -> None:
        """
        Orchestriert den Lebenszyklus eines Events:
        Erstellt Deliveries für alle Endpunkte und versucht die sofortige Auslieferung.
        """
        async with async_session_maker() as session:
            try:
                delivery_ids = await self.create_deliveries_for_event(event_id, session)
                for delivery_id in delivery_ids:
                    await self.dispatch_single_delivery(delivery_id, session)
            except Exception:  # noqa: BLE001 - Background Task darf nicht abstürzen
                pass

dispatcher = WebhookDispatcher()
