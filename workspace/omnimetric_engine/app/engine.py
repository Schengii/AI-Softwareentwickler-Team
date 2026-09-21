import asyncio
import collections
import logging
import time
import uuid
from datetime import UTC, datetime

import numpy as np

from app.models import Alert, MetricPoint, MetricStats

logger = logging.getLogger(__name__)

class RingBuffer:
    def __init__(self, max_size: int = 1000, max_age_seconds: int = 60):
        self.max_size = max_size
        self.max_age_seconds = max_age_seconds
        self.data: collections.deque[MetricPoint] = collections.deque(maxlen=max_size)

    def add(self, point: MetricPoint):
        self.data.append(point)
        self.evict_old()

    def evict_old(self):
        now = datetime.now(UTC).timestamp()
        while self.data:
            oldest_ts = self.data[0].timestamp.timestamp()
            if now - oldest_ts > self.max_age_seconds:
                self.data.popleft()
            else:
                break

    def get_values(self) -> list[float]:
        self.evict_old()
        return [p.value for p in self.data]

class AlertManager:
    def __init__(self):
        self.alerts: list[Alert] = []
        self.last_alert_time: dict[str, float] = {}
        self.cooldown_seconds = 60

    def add_alert(self, alert: Alert):
        now = time.monotonic()
        last_time = self.last_alert_time.get(alert.metric_name, 0)
        if now - last_time > self.cooldown_seconds:
            self.alerts.append(alert)
            self.last_alert_time[alert.metric_name] = now
            logger.info(f"Alert generated: {alert.message}")
        else:
            logger.debug(f"Alert deduplicated for {alert.metric_name}")

    def get_alerts(self) -> list[Alert]:
        return self.alerts

class MetricEngine:
    def __init__(self):
        self.buffers: dict[str, RingBuffer] = {}
        self.alert_manager = AlertManager()

    def ingest(self, point: MetricPoint):
        if point.name not in self.buffers:
            self.buffers[point.name] = RingBuffer()
        self.buffers[point.name].add(point)

    def get_stats(self, name: str) -> MetricStats | None:
        if name not in self.buffers:
            return None
        values = self.buffers[name].get_values()
        if not values:
            return None
        
        arr = np.array(values)
        return MetricStats(
            name=name,
            count=len(arr),
            min=float(np.min(arr)),
            max=float(np.max(arr)),
            mean=float(np.mean(arr)),
            stddev=float(np.std(arr)),
            p50=float(np.percentile(arr, 50)),
            p95=float(np.percentile(arr, 95)),
            p99=float(np.percentile(arr, 99))
        )

engine = MetricEngine()

async def anomaly_worker():
    threshold_z = 3.0
    while True:
        try:
            for name, buffer in engine.buffers.items():
                values = buffer.get_values()
                if len(values) < 10:
                    continue
                
                arr = np.array(values)
                mean = np.mean(arr)
                std = np.std(arr)
                if std == 0:
                    continue
                
                latest_val = values[-1]
                z_score = abs(latest_val - mean) / std
                
                if z_score > threshold_z:
                    alert = Alert(
                        id=str(uuid.uuid4()),
                        metric_name=name,
                        timestamp=datetime.now(UTC),
                        value=latest_val,
                        z_score=z_score,
                        threshold=threshold_z,
                        message=f"Anomaly detected for {name}: value {latest_val} has z-score {z_score:.2f}"
                    )
                    engine.alert_manager.add_alert(alert)
        except Exception as e:  # noqa: BLE001 - Worker darf nie abstürzen
            logger.error(f"Error in anomaly worker: {e}")
        
        await asyncio.sleep(5)
