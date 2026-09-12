"""
OmniQueue - Statistisches Anomalie-Erkennungsmodul für Dispatch-Ziele.
Implementiert Ring-Buffer, gleitende Durchschnitte und Z-Score-Ausreißererkennung
für Latenzen und sprunghafte Fehlerraten.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class AnomalyType(str, Enum):
    """Klassifikation der erkannten Anomalie."""
    NONE = "none"
    LATENCY_SPIKE = "latency_spike"
    ERROR_RATE_SPIKE = "error_rate_spike"
    COMBINED = "combined"


@dataclass(frozen=True)
class MetricPoint:
    """Repräsentiert einen einzelnen Dispatch-Messpunkt."""
    timestamp: float
    latency_ms: float
    is_error: bool


@dataclass
class AnomalyReport:
    """Ergebnis der statistischen Analyse eines Zielsystems."""
    target_id: str
    is_anomaly: bool
    anomaly_type: AnomalyType
    current_latency_ms: float
    mean_latency_ms: float
    std_latency_ms: float
    latency_z_score: float
    current_error_rate: float
    mean_error_rate: float
    std_error_rate: float
    error_rate_z_score: float
    sample_count: int
    message: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "is_anomaly": self.is_anomaly,
            "anomaly_type": self.anomaly_type.value,
            "current_latency_ms": round(self.current_latency_ms, 2),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "std_latency_ms": round(self.std_latency_ms, 2),
            "latency_z_score": round(self.latency_z_score, 2),
            "current_error_rate": round(self.current_error_rate, 4),
            "mean_error_rate": round(self.mean_error_rate, 4),
            "std_error_rate": round(self.std_error_rate, 4),
            "error_rate_z_score": round(self.error_rate_z_score, 2),
            "sample_count": self.sample_count,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class RingBufferMetricsWindow:
    """
    Hochperformanter FIFO-Ring-Buffer mit fester Kapazität für Streaming-Metriken.
    Verwendet collections.deque für O(1) Push/Pop Operationen.
    """

    def __init__(self, max_size: int = 100):
        if max_size <= 0:
            raise ValueError("max_size muss größer als 0 sein.")
        self.max_size = max_size
        self._buffer: deque[MetricPoint] = deque(maxlen=max_size)

    def append(self, point: MetricPoint) -> None:
        """Fügt einen neuen Messpunkt in den Ring-Buffer ein."""
        self._buffer.append(point)

    def get_latencies(self) -> list[float]:
        """Gibt alle Latenzen im aktuellen Fenster zurück."""
        return [p.latency_ms for p in self._buffer]

    def get_errors(self) -> list[int]:
        """Gibt die Fehler-Indikatoren (1 für Fehler, 0 für Erfolg) zurück."""
        return [1 if p.is_error else 0 for p in self._buffer]

    def __len__(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()


class AnomalyDetector:
    """
    Statistischer Echtzeit-Detektor für Ausreißer in Latenzen und Fehlerraten.
    Kombiniert gleitenden Durchschnitt (Moving Average), empirische Standardabweichung
    und modifizierten Z-Score zur robusten Erkennung bei Zielsystemen.
    """

    def __init__(
        self,
        window_size: int = 60,
        min_samples: int = 10,
        latency_z_threshold: float = 2.5,
        error_z_threshold: float = 2.5,
        error_rate_min_threshold: float = 0.20,
    ):
        """
        :param window_size: Maximale Anzahl Messwerte im Ring-Buffer pro Ziel.
        :param min_samples: Mindestanzahl von Messungen, bevor Anomalien gewertet werden.
        :param latency_z_threshold: Z-Score-Schwellenwert für Latenzspitzen (Standard: 2.5 Sigma).
        :param error_z_threshold: Z-Score-Schwellenwert für Fehlerraten-Spikes.
        :param error_rate_min_threshold: Absolute Mindestfehlerrate (z.B. 20%), um Fehlalarme bei niedriger Grundgesamtheit zu vermeiden.
        """
        self.window_size = window_size
        self.min_samples = min_samples
        self.latency_z_threshold = latency_z_threshold
        self.error_z_threshold = error_z_threshold
        self.error_rate_min_threshold = error_rate_min_threshold

        # Speicher für Ring-Buffer pro target_id
        self._targets: dict[str, RingBufferMetricsWindow] = {}

    def _get_or_create_buffer(self, target_id: str) -> RingBufferMetricsWindow:
        if target_id not in self._targets:
            self._targets[target_id] = RingBufferMetricsWindow(max_size=self.window_size)
        return self._targets[target_id]

    @staticmethod
    def calculate_mean_and_std(values: list[float]) -> tuple[float, float]:
        """
        Berechnet arithmetisches Mittel und Standardabweichung.
        """
        n = len(values)
        if n == 0:
            return 0.0, 0.0
        if n == 1:
            return values[0], 0.0

        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)  # Bessel-Korrektur
        return mean, math.sqrt(variance)

    def record_metric(
        self,
        target_id: str,
        latency_ms: float,
        is_error: bool,
        timestamp: float | None = None,
    ) -> AnomalyReport:
        """
        Erfasst eine neue Transaktion für ein Zielsystem, berechnet Z-Scores und
        liefert eine Anomalie-Auswertung zurück.
        """
        ts = timestamp if timestamp is not None else time.time()
        point = MetricPoint(timestamp=ts, latency_ms=max(0.0, latency_ms), is_error=is_error)
        
        buf = self._get_or_create_buffer(target_id)
        
        # Frühere Werte für Baseline-Vergleich (vor Hinzufügen des neuen Punktes)
        prior_latencies = buf.get_latencies()
        prior_errors = buf.get_errors()

        # Neuen Punkt im Ring-Buffer hinterlegen
        buf.append(point)
        current_sample_count = len(buf)

        # Baseline-Check: Haben wir genug Datenpunkte für eine statistisch signifikante Aussage?
        if len(prior_latencies) < self.min_samples:
            return AnomalyReport(
                target_id=target_id,
                is_anomaly=False,
                anomaly_type=AnomalyType.NONE,
                current_latency_ms=latency_ms,
                mean_latency_ms=latency_ms,
                std_latency_ms=0.0,
                latency_z_score=0.0,
                current_error_rate=1.0 if is_error else 0.0,
                mean_error_rate=1.0 if is_error else 0.0,
                std_error_rate=0.0,
                error_rate_z_score=0.0,
                sample_count=current_sample_count,
                message=f"Warm-Up: Noch unzureichend Samples ({current_sample_count}/{self.min_samples})",
                timestamp=ts,
            )

        # 1. Latenz-Anomalie (Z-Score)
        mean_lat, std_lat = self.calculate_mean_and_std(prior_latencies)
        # Schutz vor Division durch 0 bei konstanter Latenz (StdDev = 0)
        effective_std_lat = max(std_lat, 5.0)  # Mindest-Jitter 5ms als Regularisierung
        latency_z = (latency_ms - mean_lat) / effective_std_lat

        is_latency_spike = latency_z > self.latency_z_threshold

        # 2. Fehlerraten-Anomalie
        # Gleitende Fehlerrate über das letzte Sub-Fenster (letzte min_samples)
        recent_window_size = min(len(buf), self.min_samples)
        all_errors = buf.get_errors()
        recent_errors = all_errors[-recent_window_size:]
        current_error_rate = sum(recent_errors) / recent_window_size

        # Baseline-Fehlerrate
        mean_err, std_err = self.calculate_mean_and_std([float(e) for e in prior_errors])
        effective_std_err = max(std_err, 0.05)  # 5% Mindeststreuung
        error_z = (current_error_rate - mean_err) / effective_std_err

        # Fehlerraten-Anomalie nur dann, wenn Z-Score überschritten und Mindestfehlerrate erreicht
        is_error_spike = (
            error_z > self.error_z_threshold
            and current_error_rate >= self.error_rate_min_threshold
        )

        # Anomalie-Klassifikation
        if is_latency_spike and is_error_spike:
            anom_type = AnomalyType.COMBINED
            msg = f"Kritisch: Latenz-Spike (Z={latency_z:.2f}) und erhöhte Fehlerrate ({current_error_rate:.1%}, Z={error_z:.2f})"
        elif is_latency_spike:
            anom_type = AnomalyType.LATENCY_SPIKE
            msg = f"Latenz-Spike erkannt: {latency_ms:.1f}ms vs. Mittelwert {mean_lat:.1f}ms (Z={latency_z:.2f})"
        elif is_error_spike:
            anom_type = AnomalyType.ERROR_RATE_SPIKE
            msg = f"Fehlerraten-Spike erkannt: {current_error_rate:.1%} vs. Basis {mean_err:.1%} (Z={error_z:.2f})"
        else:
            anom_type = AnomalyType.NONE
            msg = "Systemverhalten im statistischen Normalbereich"

        return AnomalyReport(
            target_id=target_id,
            is_anomaly=(anom_type != AnomalyType.NONE),
            anomaly_type=anom_type,
            current_latency_ms=latency_ms,
            mean_latency_ms=mean_lat,
            std_latency_ms=std_lat,
            latency_z_score=latency_z,
            current_error_rate=current_error_rate,
            mean_error_rate=mean_err,
            std_error_rate=std_err,
            error_rate_z_score=error_z,
            sample_count=current_sample_count,
            message=msg,
            timestamp=ts,
        )

    def get_target_summary(self, target_id: str) -> dict | None:
        """Liefert eine Statuszusammenfassung für das Dashboard."""
        buf = self._targets.get(target_id)
        if not buf or len(buf) == 0:
            return None

        latencies = buf.get_latencies()
        errors = buf.get_errors()
        mean_lat, std_lat = self.calculate_mean_and_std(latencies)
        error_rate = sum(errors) / len(errors)

        return {
            "target_id": target_id,
            "window_size": len(buf),
            "mean_latency_ms": round(mean_lat, 2),
            "std_latency_ms": round(std_lat, 2),
            "error_rate": round(error_rate, 4),
            "total_samples": len(buf),
        }

    def reset(self, target_id: str | None = None) -> None:
        """Setzt den Metrikspeicher zurück (einzelnes Target oder alle)."""
        if target_id:
            if target_id in self._targets:
                self._targets[target_id].clear()
        else:
            self._targets.clear()


# Globales Singleton für Gateway-Worker und API
anomaly_detector = AnomalyDetector()
