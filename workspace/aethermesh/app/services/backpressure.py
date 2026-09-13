"""Adaptives Backpressure-Management, Dead-Letter-Quarantine (DLQ) und Resilienz-Mechanismen für AetherMesh."""

import logging
import secrets
import time
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def calculate_backoff_delay(
    attempt: int,
    base_delay: Optional[float] = None,
    factor: Optional[float] = None,
    jitter: bool = True,
    max_delay: float = 60.0,
) -> float:
    """Berechnet exponentielles Backoff mit kryptografisch sicherem Jitter (secrets.SystemRandom).

    Formel: base_delay * (factor ** attempt) * jitter_faktor
    """
    settings = get_settings()
    base = base_delay if base_delay is not None else settings.BASE_RETRY_DELAY_SEC
    fact = factor if factor is not None else settings.RETRY_BACKOFF_FACTOR

    # Exponentieller Anstieg
    delay = base * (fact ** max(0, attempt))
    delay = min(delay, max_delay)

    if jitter:
        # Full/Equal Jitter mit secrets.SystemRandom() (Bandit-konform, kein insecure random)
        jitter_mult = secrets.SystemRandom().uniform(0.75, 1.25)
        delay = delay * jitter_mult

    return round(max(0.0, delay), 4)


class DeadLetterQueue:
    """Quarantäne-Speicher für Jobs, die nach maximalen Retries endgültig fehlgeschlagen sind."""

    def __init__(self, max_size: int = 5000) -> None:
        self.max_size = max_size
        self._dlq: List[Dict[str, Any]] = []

    def push(
        self,
        job_id: str,
        payload: Any,
        error_reason: str,
        attempts: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fügt einen endgültig gescheiterten Job zur DLQ hinzu."""
        entry = {
            "job_id": job_id,
            "payload": payload,
            "error_reason": error_reason,
            "attempts": attempts,
            "failed_at_monotonic": time.monotonic(),
            "metadata": metadata or {},
        }
        if len(self._dlq) >= self.max_size:
            self._dlq.pop(0)  # FIFO-Verdrängung bei DLQ-Überlauf
            logger.warning("DLQ Kapazität erreicht (%d). Ältester Eintrag verworfen.", self.max_size)

        self._dlq.append(entry)
        logger.error(
            "Job %s endgültig gescheitert nach %d Versuchen in DLQ verschoben: %s",
            job_id,
            attempts,
            error_reason,
        )
        return entry

    def list_quarantine(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Liefert die neuesten DLQ-Einträge zurück."""
        return list(reversed(self._dlq[-limit:]))

    def get_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Sucht nach einem Job in der Quarantäne."""
        for item in reversed(self._dlq):
            if item["job_id"] == job_id:
                return item
        return None

    def purge(self) -> int:
        """Leert die Dead-Letter-Queue."""
        count = len(self._dlq)
        self._dlq.clear()
        return count

    def __len__(self) -> int:
        return len(self._dlq)


class BackpressureController:
    """Adaptiver Backpressure-Controller mit Hysterese-Regulierung.

    Verhindert Systemüberlastung und Kaskadenabstürze:
    - Schaltet auf Überlastung um, wenn Füllstand >= HIGH_WATERMARK (z.B. 85%)
    - Bleibt im Drosselungszustand, bis Füllstand < LOW_WATERMARK (z.B. 50%)
    - Weist eingehende Requests mit HTTP 429 Too Many Requests & Retry-After ab
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._is_throttled: bool = False
        self._last_state_change: float = time.monotonic()

    @property
    def high_watermark(self) -> float:
        return self._settings.BACKPRESSURE_HIGH_WATERMARK

    @property
    def low_watermark(self) -> float:
        return self._settings.BACKPRESSURE_LOW_WATERMARK

    @property
    def max_queue_size(self) -> int:
        return self._settings.MAX_QUEUE_SIZE

    @property
    def retry_after_seconds(self) -> int:
        return self._settings.RETRY_AFTER_SECONDS

    @property
    def is_throttled(self) -> bool:
        return self._is_throttled

    def update_state(self, current_queue_size: int) -> bool:
        """Aktualisiert den Backpressure-Status basierend auf aktuellem Füllstand und Hysterese."""
        ratio = current_queue_size / max(1, self.max_queue_size)

        if not self._is_throttled and ratio >= self.high_watermark:
            self._is_throttled = True
            self._last_state_change = time.monotonic()
            logger.warning(
                "Backpressure AKTIVIERT: Füllstand %.1f%% überschreitet High-Watermark (%.1f%%).",
                ratio * 100,
                self.high_watermark * 100,
            )
        elif self._is_throttled and ratio < self.low_watermark:
            self._is_throttled = False
            self._last_state_change = time.monotonic()
            logger.info(
                "Backpressure DEAKTIVIERT: Füllstand %.1f%% unter Low-Watermark (%.1f%%) gefallen.",
                ratio * 100,
                self.low_watermark * 100,
            )

        return self._is_throttled

    def check_backpressure(self, current_queue_size: int) -> None:
        """Prüft Auslastung und wirft bei aktiver Drosselung HTTP 429 mit Retry-After Header."""
        self.update_state(current_queue_size)
        if self._is_throttled:
            retry_after = str(self.retry_after_seconds)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"System überlastet (Backpressure aktiv). Aktuelle Warteschlange: "
                    f"{current_queue_size}/{self.max_queue_size}. Bitte später erneut versuchen."
                ),
                headers={"Retry-After": retry_after},
            )

    def get_metrics(self, current_queue_size: int) -> Dict[str, Any]:
        """Gibt detaillierten Resilienz- und Backpressure-Status zurück."""
        self.update_state(current_queue_size)
        fill_ratio = round(current_queue_size / max(1, self.max_queue_size), 4)
        return {
            "is_throttled": self._is_throttled,
            "current_queue_size": current_queue_size,
            "max_queue_size": self.max_queue_size,
            "fill_ratio": fill_ratio,
            "high_watermark": self.high_watermark,
            "low_watermark": self.low_watermark,
            "retry_after_seconds": self.retry_after_seconds,
            "seconds_since_state_change": round(time.monotonic() - self._last_state_change, 2),
        }
