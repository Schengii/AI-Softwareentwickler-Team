import math
import time
from collections import deque

from app.schemas.metric import MetricRecord, WindowAggregate


class SlidingWindowAggregator:
    """Sliding-Window-Aggregation mit zeitbasierten Deques.
    
    Verwaltet Datenpunkte pro Metrik und berechnet gleitende statistische
    Kennzahlen (Count, Sum, Min, Max, Avg, P95) über definierte Zeitfenster.
    """

    def __init__(self, windows: list[int] | None = None, max_window_seconds: int | None = None) -> None:
        # Standard-Fenster: 10s (Echtzeit), 60s (1m Kurzzeit), 300s (5m Trend)
        self.windows: list[int] = sorted(windows or [10, 60, 300])
        self.max_window: int = max_window_seconds or max(self.windows)
        # Struktur: metric_name -> deque of (timestamp, value)
        self._data: dict[str, deque] = {}
        self._latest_tags: dict[str, dict[str, str]] = {}

    def _get_key(self, metric: MetricRecord) -> str:
        # Basisschlüssel ist der Metrikname. Falls tags vorhanden sind, optional getrennt oder flat.
        return metric.name

    def add(self, metric: MetricRecord) -> None:
        """Fügt einen Metrik-Datenpunkt hinzu und entfernt veraltete Datenpunkte."""
        key = self._get_key(metric)
        if key not in self._data:
            self._data[key] = deque()

        now = metric.timestamp
        self._data[key].append((now, float(metric.value)))
        if metric.tags:
            self._latest_tags[key] = metric.tags

        self._evict_expired(key, now)

    def _evict_expired(self, key: str, current_time: float) -> None:
        """Entfernt Datenpunkte, die älter als das maximale Fenster sind."""
        dq = self._data.get(key)
        if not dq:
            return

        cutoff = current_time - self.max_window
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def get_aggregate(self, metric_name: str, window_seconds: int, reference_time: float | None = None) -> WindowAggregate | None:
        """Berechnet Kennzahlen für eine Metrik über das angegebene Zeitfenster."""
        dq = self._data.get(metric_name)
        if not dq:
            return None

        now = reference_time if reference_time is not None else time.time()
        cutoff = now - window_seconds

        # Werte im Fenster filtern (Deque ist nach Zeit sortiert)
        values: list[float] = []
        for ts, val in reversed(dq):
            if ts >= cutoff:
                values.append(val)
            else:
                break

        if not values:
            return None

        # values ist in umgekehrter Reihenfolge, latest ist values[0]
        latest_val = values[0]
        count = len(values)
        total_sum = sum(values)
        min_val = min(values)
        max_val = max(values)
        avg_val = total_sum / count

        # P95 Berechnung
        sorted_vals = sorted(values)
        p95_idx = max(0, math.ceil(0.95 * count) - 1)
        p95_val = sorted_vals[p95_idx]

        return WindowAggregate(
            name=metric_name,
            window_seconds=window_seconds,
            count=count,
            sum=round(total_sum, 4),
            min=round(min_val, 4),
            max=round(max_val, 4),
            avg=round(avg_val, 4),
            p95=round(p95_val, 4),
            latest_value=round(latest_val, 4),
            timestamp=now,
            tags=self._latest_tags.get(metric_name, {})
        )

    def get_all_aggregates(self, metric_name: str, reference_time: float | None = None) -> list[WindowAggregate]:
        """Liefert Aggregate über alle konfigurierten Fenster für eine Metrik."""
        aggregates = []
        for w in self.windows:
            agg = self.get_aggregate(metric_name, window_seconds=w, reference_time=reference_time)
            if agg is not None:
                aggregates.append(agg)
        return aggregates

    def get_tracked_metrics(self) -> list[str]:
        """Gibt alle aktuell nachverfolgten Metriknamen zurück."""
        return list(self._data.keys())

    def clear(self) -> None:
        """Löscht alle gespeicherten Datenpunkte."""
        self._data.clear()
        self._latest_tags.clear()
