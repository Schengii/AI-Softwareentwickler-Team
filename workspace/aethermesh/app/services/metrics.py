"""AetherMesh Engine - Metrics Aggregator Service.

Sammelt und aggregiert Durchsatz-, Latenz- und Fehler-Metriken
für Monitoring, Backpressure-Steuerung und Dashboard-Streaming.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class MetricsAggregator:
    """Aggregiert Metriken über verarbeitete Jobs, Fehlerraten und System-Durchsatz."""

    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_dlq: int = 0
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    start_time: float = field(default_factory=time.monotonic)

    def record_job_submission(self, job_id: str | None = None) -> None:
        """Registriert die Einreichung eines neuen Jobs."""
        self.total_submitted += 1

    async def record_job_success(self, job_id: str | None = None, latency: float = 0.0) -> None:
        """Registriert die erfolgreiche Beendigung eines Jobs."""
        self.total_completed += 1
        if latency > 0:
            self.latencies.append(latency)
        self.history.append({
            "event": "success",
            "job_id": str(job_id),
            "timestamp": time.time(),
        })

    async def record_job_dlq(self, job_id: str | None = None, reason: str | None = None) -> None:
        """Registriert die Quarantäne eines Jobs in der Dead-Letter-Queue."""
        self.total_dlq += 1
        self.total_failed += 1
        self.history.append({
            "event": "dlq",
            "job_id": str(job_id),
            "reason": reason,
            "timestamp": time.time(),
        })

    def record_job_failure(self, job_id: str | None = None, reason: str | None = None) -> None:
        """Registriert einen temporären oder permanenten Job-Fehlschlag."""
        self.total_failed += 1

    def get_metrics(self) -> dict[str, Any]:
        """Gibt aktuelle Systemmetriken als Dictionary zurück."""
        uptime = max(0.001, time.monotonic() - self.start_time)
        avg_latency = (
            sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        )
        throughput = self.total_completed / uptime

        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_dlq": self.total_dlq,
            "average_latency_sec": round(avg_latency, 4),
            "throughput_jobs_per_sec": round(throughput, 2),
            "uptime_seconds": round(uptime, 2),
        }

    def get_system_metrics(self) -> dict[str, Any]:
        """Alias für get_metrics zur Anbindung an Backpressure-Controller."""
        return self.get_metrics()

    def reset(self) -> None:
        """Setzt die Metrikzähler zurück (z. B. für Test-Isolierung)."""
        self.total_submitted = 0
        self.total_completed = 0
        self.total_failed = 0
        self.total_dlq = 0
        self.latencies.clear()
        self.history.clear()
        self.start_time = time.monotonic()
