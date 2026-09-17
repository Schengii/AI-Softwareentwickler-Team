import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from app.schemas.metric import BroadcastEvent, MetricRecord, WindowAggregate
from app.services.event_bus import EventBus, get_event_bus
from app.services.sliding_window import SlidingWindowAggregator

logger = logging.getLogger(__name__)

# Typ für Alert-Evaluation Callback: async def evaluate(metric, aggregates) -> None
AlertCallback = Callable[[MetricRecord, list[WindowAggregate]], Coroutine[Any, Any, None]]


class IngestionPipeline:
    """Asynchrone Ingestion-Pipeline mit Sliding-Window-Aggregation und Event-Broadcasting.
    
    Trennt HTTP-Ingestion durch eine asyncio.Queue vom Aggregations- und Alerting-Processing.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        aggregator: SlidingWindowAggregator | None = None,
        max_queue_size: int = 50_000,
        batch_size: int = 100,
        flush_interval_sec: float = 0.05
    ) -> None:
        self.event_bus = event_bus or get_event_bus()
        self.aggregator = aggregator or SlidingWindowAggregator()
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec

        self._queue: asyncio.Queue[MetricRecord] | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._alert_handlers: list[AlertCallback] = []

        # Interne Durchsatz- & Health-Zähler
        self.metrics_received_total: int = 0
        self.metrics_processed_total: int = 0
        self.metrics_dropped_total: int = 0
        self.dead_letter_queue: list[dict] = []
        self._max_dlq_size: int = 1000

    def _get_queue(self) -> asyncio.Queue[MetricRecord]:
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.max_queue_size)
        return self._queue

    def register_alert_handler(self, handler: AlertCallback) -> None:
        """Registriert einen asynchronen Handler zur Schwellwert- und Alert-Prüfung."""
        self._alert_handlers.append(handler)

    async def enqueue(self, metric: MetricRecord) -> bool:
        """Nimmt Metriken mit Sub-Millisekunden-Latenz non-blocking entgegen.
        
        Gibt True zurück wenn erfolgreich in die Queue eingereiht,
        False wenn die Queue voll ist (Backpressure/Drop).
        """
        self.metrics_received_total += 1
        q = self._get_queue()
        try:
            q.put_nowait(metric)
            return True
        except asyncio.QueueFull:
            self.metrics_dropped_total += 1
            logger.warning("Ingestion-Queue voll (%d Items). Metrik %s verworfen.", self.max_queue_size, metric.name)
            if len(self.dead_letter_queue) < self._max_dlq_size:
                self.dead_letter_queue.append({
                    "reason": "QueueFull",
                    "metric": metric.model_dump(),
                    "dropped_at": time.time()
                })
            return False

    async def start(self) -> None:
        """Startet den Hintergrund-Worker im laufenden Event-Loop."""
        if self._running:
            return
        self._running = True
        self._get_queue()  # Initialisiert Queue im aktiven Loop
        self._worker_task = asyncio.create_task(self._worker_loop(), name="hyperion_ingestion_worker")
        logger.info("Ingestion-Pipeline Worker erfolgreich gestartet.")

    async def stop(self) -> None:
        """Beendet den Worker geordnet (Graceful Shutdown mit Queue-Drain)."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Ingestion-Pipeline Worker gestoppt.")

    async def _worker_loop(self) -> None:
        """Worker-Schleife zur Entnahme und Verarbeitung von Metriken mit Micro-Batching."""
        q = self._get_queue()
        while self._running:
            try:
                # Warte auf das erste Item
                metric = await q.get()
                batch = [metric]

                # Versuche weitere Items bis batch_size abzugreifen
                while len(batch) < self.batch_size:
                    try:
                        batch.append(q.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                await self._process_batch(batch)

                for _ in batch:
                    q.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unerwarteter Fehler im Ingestion-Worker: %s", e, exc_info=True)
                await asyncio.sleep(0.01)

    async def _process_batch(self, batch: list[MetricRecord]) -> None:
        """Verarbeitet einen Batch von Metriken: Sliding Window, Alerting, EventBus."""
        now = time.time()
        for metric in batch:
            try:
                # 1. Sliding-Window-Aggregation aktualisieren
                self.aggregator.add(metric)
                self.metrics_processed_total += 1

                # 2. Gleitende Aggregate berechnen
                aggregates = self.aggregator.get_all_aggregates(metric.name, reference_time=now)

                # 3. Alert-Regeln evaluieren (falls Handler registriert)
                for handler in self._alert_handlers:
                    try:
                        await handler(metric, aggregates)
                    except Exception as handler_err:  # noqa: BLE001 - Handler-Fehler isolieren
                        logger.error("Fehler beim Ausführen des Alert-Handlers: %s", handler_err)

                # 4. WebSocket Broadcast Events an Event-Bus publizieren
                # a) Raw-Metrik-Event
                metric_event = BroadcastEvent(
                    type="metric",
                    timestamp=metric.timestamp,
                    data=metric.model_dump()
                )
                await self.event_bus.publish(metric_event)

                # b) Aggregierte Fenster-Events
                for agg in aggregates:
                    agg_event = BroadcastEvent(
                        type="aggregate",
                        timestamp=agg.timestamp,
                        data=agg.model_dump()
                    )
                    await self.event_bus.publish(agg_event)

            except Exception as err:  # noqa: BLE001 - Fehlerhafte Metriken in DLQ überführen
                logger.error("Fehler bei der Metrik-Verarbeitung (%s): %s", metric.name, err)
                if len(self.dead_letter_queue) < self._max_dlq_size:
                    self.dead_letter_queue.append({
                        "reason": str(err),
                        "metric": metric.model_dump(),
                        "dropped_at": time.time()
                    })

    def get_stats(self) -> dict:
        """Liefert Betriebs- und Durchsatzstatistiken der Pipeline."""
        q = self._get_queue()
        return {
            "queue_size": q.qsize(),
            "max_queue_size": self.max_queue_size,
            "metrics_received_total": self.metrics_received_total,
            "metrics_processed_total": self.metrics_processed_total,
            "metrics_dropped_total": self.metrics_dropped_total,
            "dlq_size": len(self.dead_letter_queue),
            "tracked_metrics": self.aggregator.get_tracked_metrics(),
            "subscribers": self.event_bus.subscriber_count()
        }


_default_pipeline: IngestionPipeline | None = None


def get_pipeline() -> IngestionPipeline:
    """Factory-Accessor für die globale IngestionPipeline."""
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = IngestionPipeline()
    return _default_pipeline
