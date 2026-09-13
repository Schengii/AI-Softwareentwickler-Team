from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class IngestionMetric:
    timestamp: float | datetime | str = 0.0
    request_count: float = 0.0
    rate: float = 0.0
    tenant_id: str = ""

    def get_value(self) -> float:
        if self.request_count != 0.0:
            return float(self.request_count)
        return float(self.rate)


class AnomalyDetector:
    """Statistischer Z-Score-Anomaliedetektor für Ingestion-Metriken."""

    def __init__(self, window_size: int = 20, z_score_threshold: float = 2.5) -> None:
        self.window_size = window_size
        self.z_score_threshold = z_score_threshold
        self.history: deque[float] = deque(maxlen=window_size)

    def record_metric(self, metric: IngestionMetric) -> None:
        """Nimmt eine Metrik ausschließlich in die Baseline-Historie auf, ohne eine Anomalie-
        Bewertung durchzuführen - z.B. zum Aufbau der initialen Baseline, bevor check_anomaly()
        zum ersten Mal für eine echte Bewertung aufgerufen wird."""
        self.history.append(metric.get_value())

    def check_anomaly(self, metric: IngestionMetric) -> tuple[bool, float]:
        val = metric.get_value()
        if len(self.history) < 2:
            self.history.append(val)
            return False, 0.0

        mean = sum(self.history) / len(self.history)
        variance = sum((x - mean) ** 2 for x in self.history) / len(self.history)
        std_dev = math.sqrt(variance)

        self.history.append(val)

        # Eine perfekt konstante Baseline (std_dev == 0, z.B. nach ausschließlichem
        # record_metric()-Seeding identischer Werte) darf NICHT jede noch so kleine
        # Abweichung als Anomalie mit unendlichem Z-Score werten - das würde bereits normales
        # Rauschen (z.B. +5% Request-Last) fälschlich melden. Ein relativer Mindest-"Rauschpegel"
        # von 10% des Mittelwerts verhindert die Division durch null, ohne echte Ausreißer
        # (Größenordnungen über der Baseline) zu übersehen.
        std_dev = max(std_dev, abs(mean) * 0.1, 1e-9)

        z_score = abs(val - mean) / std_dev
        is_anomaly = z_score >= self.z_score_threshold
        return is_anomaly, z_score


# Singleton Instanz laut interface_contract.json
anomaly_detector = AnomalyDetector()
