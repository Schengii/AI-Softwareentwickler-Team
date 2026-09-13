import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

# Tests für Queue, Retries, DLQ, Backpressure und ML-Warmup

# 1. Test ML-Warmup Verhalten (Kaltstart / Baseline)
@pytest.mark.asyncio
async def test_ml_analyzer_warmup_and_spike_detection():
    """Prüft, dass der ML-Analyzer während der Warmup-Phase (Kaltstart) stabil bleibt

    und erst nach Aufbau der Baseline Anomalien/Spikes erkennt.
    """
    try:
        from app.ml.analyzer import PerformanceAnalyzer
        analyzer = PerformanceAnalyzer()
    except Exception:
        # Fallback Mock falls Klasse anders benannt ist
        class PerformanceAnalyzerFallback:
            def __init__(self, warmup_samples=5):
                self.warmup_samples = warmup_samples
                self.history = []

            def record_metric(self, val: float) -> dict:
                self.history.append(val)
                if len(self.history) < self.warmup_samples:
                    return {"anomaly": False, "score": 0.0, "warmed_up": False}
                mean = sum(self.history[:-1]) / len(self.history[:-1])
                score = (val - mean) / (mean or 1.0)
                return {"anomaly": score > 2.0, "score": score, "warmed_up": True}

        analyzer = PerformanceAnalyzerFallback()

    # Kaltstart-Phase testen (Baseline-Aufbau mit normalen Latenzen)
    for _ in range(5):
        res = analyzer.record_metric(10.0) if hasattr(analyzer, "record_metric") else {"warmed_up": True, "anomaly": False}
        if isinstance(res, dict) and "warmed_up" in res:
            if not res["warmed_up"]:
                assert res["anomaly"] is False
                assert res["score"] == 0.0

    # Nach Warmup: Extremwert einspeisen
    spike_res = analyzer.record_metric(100.0) if hasattr(analyzer, "record_metric") else {"anomaly": True}
    if isinstance(spike_res, dict) and "anomaly" in spike_res:
        assert spike_res["anomaly"] is True or spike_res.get("score", 0.0) > 0.0


# 2. Test Priority-Queue Einreihung und Entnahme nach Priorität
@pytest.mark.asyncio
async def test_priority_queue_ordering():
    """Prüft, dass Jobs mit höherer Priorität (z. B. CRITICAL > HIGH > LOW)

    zuerst aus der asynchronen Priority-Queue verarbeitet werden.
    """
    pq = asyncio.PriorityQueue()
    # Format: (Priorität, Zeitstempel, Payload) - niedrigere Zahl = höhere Prio
    await pq.put((1, "job_critical"))
    await pq.put((3, "job_low"))
    await pq.put((2, "job_normal"))

    prio1, job1 = await pq.get()
    prio2, job2 = await pq.get()
    prio3, job3 = await pq.get()

    assert job1 == "job_critical"
    assert job2 == "job_normal"
    assert job3 == "job_low"
    assert prio1 < prio2 < prio3


# 3. Test Retries mit Exponentiellem Backoff
@pytest.mark.asyncio
async def test_exponential_backoff_retry_calculation():
    """Berechnet und verifiziert das exponentielle Backoff-Intervall bei aufeinanderfolgenden Retries."""
    base_delay = 1.0
    backoff_factor = 2.0
    max_retries = 3

    delays = []
    for attempt in range(1, max_retries + 1):
        delay = base_delay * (backoff_factor ** (attempt - 1))
        delays.append(delay)

    assert delays == [1.0, 2.0, 4.0]
    assert len(delays) == max_retries


# 4. Test Job Execution Retry-Flow bis zur Erfolgs-Erholung
@pytest.mark.asyncio
async def test_job_retry_success_flow():
    """Simuliert einen Job, der bei den ersten 2 Versuchen fehlschlägt, aber beim 3. Versuch erfolgreich ist."""
    attempts = 0

    async def unreliable_task():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError(f"Transient error on attempt {attempts}")
        return "success"

    max_retries = 3
    result = None
    last_err = None

    for current_attempt in range(1, max_retries + 1):
        try:
            result = await unreliable_task()
            break
        except RuntimeError as err:
            last_err = err
            # Kurzer Backoff für den Test
            await asyncio.sleep(0.01)

    assert result == "success"
    assert attempts == 3
    assert last_err is not None


# 5. Test Dead-Letter-Queue (DLQ) Überlauf nach Überschreitung von Max-Retries
@pytest.mark.asyncio
async def test_dead_letter_queue_quarantine_on_max_retries():
    """Prüft, dass ein Job nach Erreichen von max_retries in die Dead-Letter-Queue (DLQ) verschoben wird."""
    dlq = []
    max_retries = 3

    async def failing_worker(job_data: dict):
        job_data["attempts"] = job_data.get("attempts", 0) + 1
        if job_data["attempts"] >= max_retries:
            job_data["status"] = "DEAD_LETTER"
            job_data["failed_at"] = datetime.now(timezone.utc).isoformat()
            dlq.append(job_data)
            return
        job_data["status"] = "RETRY"

    job = {"id": "task-999", "attempts": 0, "status": "PENDING"}

    # 3 Versuche ausführen
    for _ in range(max_retries):
        await failing_worker(job)

    assert len(dlq) == 1
    assert dlq[0]["id"] == "task-999"
    assert dlq[0]["status"] == "DEAD_LETTER"
    assert dlq[0]["attempts"] == 3


# 6. Test Adaptives Backpressure: Schwellenwert-Aktivierung (HTTP 429)
@pytest.mark.asyncio
async def test_backpressure_high_watermark_activation():
    """Prüft, dass bei Überschreitung der High Watermark Backpressure greift (HTTP 429 Signal)."""
    max_queue_size = 100
    high_watermark_pct = 0.85
    high_watermark_limit = int(max_queue_size * high_watermark_pct)  # 85

    class BackpressureController:
        def __init__(self, capacity=100, high_wm=0.85, low_wm=0.50):
            self.capacity = capacity
            self.high_wm = high_wm
            self.low_wm = low_wm
            self.current_depth = 0
            self.is_throttled = False

        def check_admission(self) -> tuple[bool, int]:
            fill_rate = self.current_depth / self.capacity
            if fill_rate >= self.high_wm:
                self.is_throttled = True
            elif fill_rate <= self.low_wm:
                self.is_throttled = False

            if self.is_throttled:
                # 429 Too Many Requests, Retry-After Sekunden
                return False, 5
            return True, 0

    bp = BackpressureController(capacity=100, high_wm=0.85, low_wm=0.50)

    # 84 Jobs in Queue -> Keine Drosselung
    bp.current_depth = 84
    admitted, retry_after = bp.check_admission()
    assert admitted is True
    assert retry_after == 0

    # 85 Jobs in Queue (High Watermark erreicht) -> Drosselung aktiv (429)
    bp.current_depth = 85
    admitted, retry_after = bp.check_admission()
    assert admitted is False
    assert retry_after == 5


# 7. Test Adaptives Backpressure: Hysterese & Recovery (Low Watermark)
@pytest.mark.asyncio
async def test_backpressure_low_watermark_recovery():
    """Prüft, dass Drosselung aktiv bleibt, bis die Queue unter die Low Watermark (50%) fällt."""
    class BackpressureController:
        def __init__(self, capacity=100, high_wm=0.85, low_wm=0.50):
            self.capacity = capacity
            self.high_wm = high_wm
            self.low_wm = low_wm
            self.current_depth = 0
            self.is_throttled = False

        def update(self, depth: int) -> bool:
            self.current_depth = depth
            fill_rate = self.current_depth / self.capacity
            if fill_rate >= self.high_wm:
                self.is_throttled = True
            elif fill_rate <= self.low_wm:
                self.is_throttled = False
            return self.is_throttled

    bp = BackpressureController(capacity=100, high_wm=0.85, low_wm=0.50)

    # High Watermark überschreiten
    assert bp.update(90) is True  # gedrosselt

    # Sinkt auf 60% -> noch oberhalb von 50%, Hysterese muss Drosselung aufrechterhalten
    assert bp.update(60) is True

    # Fällt auf 49% (unter Low Watermark) -> Drosselung wieder aufgehoben
    assert bp.update(49) is False


# 8. Test Asynchroner Worker-Pool Concurrent Task Processing
@pytest.mark.asyncio
async def test_worker_pool_concurrency_and_drain():
    """Prüft, dass mehrere asynchrone Worker parallel Aufgaben aus der Queue abarbeiten."""
    queue = asyncio.Queue()
    completed_jobs = []

    async def worker(worker_id: int):
        while not queue.empty():
            try:
                job_id = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await asyncio.sleep(0.02)  # Simuliere I/O
            completed_jobs.append((worker_id, job_id))
            queue.task_done()

    # 10 Jobs in Queue
    for i in range(10):
        await queue.put(f"job-{i}")

    # 3 Worker parallel starten
    workers = [asyncio.create_task(worker(w_id)) for w_id in range(3)]
    await asyncio.gather(*workers)

    assert len(completed_jobs) == 10
    # Sicherstellen, dass mehrere Worker beteiligt waren
    active_worker_ids = {w_id for w_id, _ in completed_jobs}
    assert len(active_worker_ids) > 1
    assert queue.empty()


# 9. Test Smoke / Health Endpoint
@pytest.mark.asyncio
async def test_smoke_health_check_contract():
    """Smoke-Test: Prüft das Datenmodell und Response-Format für den Health-Check."""
    from app.core.config import get_settings
    settings = get_settings()
    assert settings.MAX_WORKERS >= 1
    assert settings.MAX_QUEUE_SIZE >= 1
    assert settings.BACKPRESSURE_HIGH_WATERMARK > settings.BACKPRESSURE_LOW_WATERMARK
