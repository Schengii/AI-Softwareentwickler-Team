import math
import time
from collections import deque
from typing import Deque, Dict, List, Optional
from app.models.schemas import MetricItem, WindowAggregate


class SlidingWindowAggregator:
    """Aggregiert Metrikdaten innerhalb konfigurierbarer gleitender Zeitfenster."""

    def __init__(self, max_retention_seconds: float = 3600.0) -> None:
        self.max_retention_seconds = max_retention_seconds
        # Pro Metrik-Name speichern wir eine deque von (timestamp, value, is_error)
        self._buffers: Dict[str, Deque[tuple[float, float, bool]]] = {}

    def add_metric(self, metric: MetricItem) -> None:
        """Fügt einen neuen Metrik-Datenpunkt zum Puffer hinzu."""
        if metric.name not in self._buffers:
            self._buffers[metric.name] = deque()

        self._buffers[metric.name].append((metric.timestamp, metric.value, metric.is_error))
        self._evict_old(metric.name, metric.timestamp)

    def _evict_old(self, metric_name: str, current_ts: float) -> None:
        """Entfernt Datenpunkte, die älter als max_retention_seconds sind."""
        buffer = self._buffers.get(metric_name)
        if not buffer:
            return
        cutoff = current_ts - self.max_retention_seconds
        while buffer and buffer[0][0] < cutoff:
            buffer.popleft()

    def get_aggregate(self, metric_name: str, window_seconds: float = 60.0) -> WindowAggregate:
        """Berechnet Kennzahlen (p50, p95, p99, Durchsatz, Fehlerrate, min, max, avg, sum) im Fenster."""
        now = time.time()
        buffer = self._buffers.get(metric_name, deque())
        cutoff = now - window_seconds

        # Relevante Werte filtern
        recent = [(ts, val, err) for ts, val, err in buffer if ts >= cutoff]

        if not recent:
            return WindowAggregate(
                metric_name=metric_name,
                window_seconds=window_seconds,
                count=0,
                throughput=0.0,
                error_rate=0.0,
                min=0.0,
                max=0.0,
                avg=0.0,
                sum=0.0,
                p50=0.0,
                p95=0.0,
                p99=0.0,
            )

        values = sorted([val for _, val, _ in recent])
        count = len(values)
        total_sum = sum(values)
        avg = total_sum / count
        min_val = values[0]
        max_val = values[-1]

        error_count = sum(1 for _, _, err in recent if err)
        error_rate = error_count / count if count > 0 else 0.0

        # Durchsatz: Anzahl Events geteilt durch Zeitfensterdauer
        effective_window = max(window_seconds, 1.0)
        throughput = count / effective_window

        def percentile(p: float) -> float:
            if not values:
                return 0.0
            idx = int(math.ceil((p / 100.0) * count)) - 1
            idx = max(0, min(idx, count - 1))
            return values[idx]

        return WindowAggregate(
            metric_name=metric_name,
            window_seconds=window_seconds,
            count=count,
            throughput=round(throughput, 4),
            error_rate=round(error_rate, 4),
            min=round(min_val, 4),
            max=round(max_val, 4),
            avg=round(avg, 4),
            sum=round(total_sum, 4),
            p50=round(percentile(50), 4),
            p95=round(percentile(95), 4),
            p99=round(percentile(99), 4),
        )


# Singleton-Instanz laut Schnittstellenvertrag
aggregator_service = SlidingWindowAggregator()
