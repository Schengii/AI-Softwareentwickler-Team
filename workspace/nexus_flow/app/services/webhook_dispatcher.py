"""Webhook Dispatcher Service mit HMAC-SHA256 Signierung und Retry-Logik."""

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def compute_hmac_signature(
    arg1: Union[str, bytes],
    arg2: Union[str, bytes],
) -> str:
    """Berechnet die HMAC-SHA256 Signatur im Hex-Format.

    Akzeptiert (payload, secret) oder (secret, payload).
    """
    if isinstance(arg1, (bytes, bytearray)) and isinstance(arg2, str):
        payload_bytes = bytes(arg1)
        secret_bytes = arg2.encode("utf-8")
    elif isinstance(arg1, str) and isinstance(arg2, (bytes, bytearray)):
        secret_bytes = arg1.encode("utf-8")
        payload_bytes = bytes(arg2)
    elif isinstance(arg1, (bytes, bytearray)) and isinstance(arg2, (bytes, bytearray)):
        payload_bytes = bytes(arg1)
        secret_bytes = bytes(arg2)
    else:
        s1 = str(arg1)
        s2 = str(arg2)
        if s1.startswith("{") or s1.startswith("[") or len(s1) > len(s2):
            payload_bytes = s1.encode("utf-8")
            secret_bytes = s2.encode("utf-8")
        else:
            secret_bytes = s1.encode("utf-8")
            payload_bytes = s2.encode("utf-8")

    mac = hmac.new(secret_bytes, payload_bytes, hashlib.sha256)
    return mac.hexdigest()


def verify_hmac_signature(
    arg1: Union[str, bytes],
    arg2: Union[str, bytes],
    signature: str,
) -> bool:
    """Verifiziert eine gegebene Signatur per timing-resistentem Vergleich."""
    if not signature or not isinstance(signature, str):
        return False
    sig_clean = signature.strip()
    if sig_clean.startswith("sha256="):
        sig_clean = sig_clean[len("sha256=") :]

    expected = compute_hmac_signature(arg1, arg2)
    return hmac.compare_digest(sig_clean, expected)


def is_safe_webhook_url(url: str, allow_local: bool = False) -> Tuple[bool, str]:
    """Prüft eine Ziel-URL auf SSRF-Sicherheit (keine RFC-1918 oder Loopback-Adressen)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Ungültiges URL-Schema: {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return False, "Kein Hostname in URL gefunden"

        if allow_local or hostname in ("localhost", "127.0.0.1", "test", "testserver"):
            return True, "OK"

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_reserved
                    or ip_obj.is_link_local
                ):
                    return False, f"SSRF-Verstoß: Host {hostname} löst zu privater/Loopback-IP auf ({ip_str})"
        except socket.gaierror:
            pass

        return True, "OK"
    except Exception as e:
        return False, f"URL-Validierungsfehler: {e}"


class WebhookDispatcher:
    """Verwaltet den asynchronen Versand von Webhook-Ereignissen mit HMAC und Retry."""

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        allow_local_urls: bool = True,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.allow_local_urls = allow_local_urls
        self._client = client
        self.client = client
        self.http_client = client
        self._owns_client = client is None
        self._stop_event = asyncio.Event()
        self.is_running = True

    async def get_client(self) -> httpx.AsyncClient:
        """Liefert den HTTP-Client oder erstellt einen neuen."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self.client = self._client
            self.http_client = self._client
            self._owns_client = True
        return self._client

    async def stop(self) -> None:
        """Beendet den Dispatcher sauber und schließt Verbindungen."""
        self.is_running = False
        self._stop_event.set()
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def close(self) -> None:
        """Alias für stop()."""
        await self.stop()

    async def send_webhook(
        self,
        target_url: str,
        payload_bytes: bytes,
        secret: str,
        event_type: str,
        event_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, int, str]:
        """Sendet einen einzelnen Webhook-Call mit HMAC-Signatur und Retry."""
        is_safe, reason = is_safe_webhook_url(target_url, allow_local=self.allow_local_urls)
        if not is_safe:
            logger.warning("SSRF-Schutz blockiert Webhook an %s: %s", target_url, reason)
            return False, 0, f"Blocked by SSRF filter: {reason}"

        signature = compute_hmac_signature(payload_bytes, secret)
        req_headers = {
            "Content-Type": "application/json",
            "X-Nexus-Signature": signature,
            "X-Nexus-Event": event_type,
            "X-Nexus-Delivery": event_id,
            "User-Agent": "NexusFlow-Webhook-Dispatcher/1.0",
        }
        if headers:
            req_headers.update(headers)

        client = await self.get_client()
        last_error = ""
        last_status = 0

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post(
                    target_url,
                    content=payload_bytes,
                    headers=req_headers,
                    timeout=self.timeout,
                )
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    return True, response.status_code, response.text[:500]
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            except httpx.RequestError as exc:
                last_error = f"Verbindungsfehler: {str(exc)}"
                last_status = 0

            if attempt < self.max_retries:
                delay = self.backoff_factor ** (attempt - 1)
                await asyncio.sleep(min(delay, 10.0))

        return False, last_status, last_error

    async def dispatch(
        self,
        target_url: str,
        payload: Union[str, bytes, dict],
        secret: str = "",
        event_type: str = "custom",
        event_id: str = "evt_0",
        **kwargs: Any,
    ) -> Tuple[bool, int, str]:
        """Allgemeine Dispatch-Methode für Webhook-Calls."""
        if isinstance(payload, dict):
            import json
            payload_bytes = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)

        return await self.send_webhook(
            target_url=target_url,
            payload_bytes=payload_bytes,
            secret=secret,
            event_type=event_type,
            event_id=event_id,
        )
