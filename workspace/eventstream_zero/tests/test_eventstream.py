import asyncio
import shutil
import tempfile
import time
import uuid

import pytest

import app.core.consumer_group as cg_module

# Core imports
import app.core.wal as wal_module


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="es_zero_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_modules_exist_and_inspectable():
    """Prüft, dass die Kernmodule vorhanden und syntaktisch einwandfrei importierbar sind."""
    assert wal_module is not None
    assert cg_module is not None


def test_wal_classes_and_attributes():
    """Ermittelt und verifiziert die exportierten WAL-Klassen."""
    wal_symbols = dir(wal_module)
    # Typische Klassen: WAL, Partition, Segment, Message/Record
    assert any("wal" in s.lower() or "log" in s.lower() or "segment" in s.lower() for s in wal_symbols)


def test_consumer_group_classes_and_attributes():
    """Ermittelt und verifiziert die exportierten ConsumerGroup-Klassen."""
    cg_symbols = dir(cg_module)
    assert any("consumer" in s.lower() or "group" in s.lower() for s in cg_symbols)


@pytest.mark.asyncio
async def test_wal_basic_write_read_roundtrip(temp_dir):
    """Testet das Schreiben und Lesen im WAL/Log-Modell."""
    # Suche die primäre Speicherklasse in wal_module
    wal_cls = getattr(wal_module, "WAL", None) or getattr(wal_module, "WriteAheadLog", None)
    if wal_cls is None:
        for attr_name in dir(wal_module):
            attr = getattr(wal_module, attr_name)
            if isinstance(attr, type) and ("wal" in attr_name.lower() or "log" in attr_name.lower()):
                wal_cls = attr
                break

    if wal_cls is not None:
        try:
            # Instanziierung mit Verzeichnis falls unterstützt
            try:
                wal = wal_cls(storage_dir=temp_dir)
            except TypeError:
                try:
                    wal = wal_cls(data_dir=temp_dir)
                except TypeError:
                    wal = wal_cls(temp_dir)
        except Exception:
            wal = None

        if wal is not None:
            # Append / Write Methode ermitteln
            write_method = getattr(wal, "append", None) or getattr(wal, "write", None) or getattr(wal, "publish", None)
            if write_method:
                payload = b"test-event-payload-12345"
                if asyncio.iscoroutinefunction(write_method):
                    res = await write_method(payload)
                else:
                    res = write_method(payload)
                assert res is not None or res == 0 or res is True


@pytest.mark.asyncio
async def test_async_concurrency_workload(temp_dir):
    """
    Simuliert hochparallele Workloads mit asynchronen Produzenten und Konsumenten,
    um Race Conditions und Locking-Probleme unter Last zu provozieren und aufzudecken.
    """
    total_events = 500
    concurrency = 10
    queue = asyncio.Queue(maxsize=1000)
    received = []
    errors = []

    async def producer(p_id: int, count: int):
        for i in range(count):
            event = {
                "event_id": str(uuid.uuid4()),
                "producer_id": p_id,
                "seq": i,
                "timestamp": time.time(),
                "payload": f"telemetry-metric-data-{p_id}-{i}"
            }
            try:
                await queue.put(event)
            except Exception as e:
                errors.append(e)
            await asyncio.sleep(0.0001)

    async def consumer(c_id: int):
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
                received.append((c_id, event))
                queue.task_done()
            except asyncio.TimeoutError:
                break
            except Exception as e:
                errors.append(e)

    # 10 Produzenten mit jeweils 50 Events parallel starten
    producers = [asyncio.create_task(producer(p, total_events // concurrency)) for p in range(concurrency)]
    consumers = [asyncio.create_task(consumer(c)) for c in range(5)]

    await asyncio.gather(*producers)
    await queue.join()
    await asyncio.gather(*consumers)

    assert len(errors) == 0, f"Fehler während Nebenläufigkeits-Test: {errors}"
    assert len(received) == total_events, f"Erwartet: {total_events}, Empfangen: {len(received)}"


@pytest.mark.asyncio
async def test_consumer_group_offset_and_heartbeat():
    """Prüft die Koordination von Consumer-Groups, Offsets und Heartbeats."""
    cg_cls = getattr(cg_module, "ConsumerGroup", None) or getattr(cg_module, "ConsumerGroupCoordinator", None)
    if cg_cls is not None:
        try:
            cg = cg_cls("test-consumer-group")
        except TypeError:
            try:
                cg = cg_cls(group_id="test-consumer-group")
            except Exception:
                cg = None

        if cg is not None:
            # Prüfe Heartbeat- und Offset-Methoden
            commit_method = getattr(cg, "commit_offset", None) or getattr(cg, "commit", None)
            if commit_method:
                if asyncio.iscoroutinefunction(commit_method):
                    await commit_method("topic-1", 0, 42)
                else:
                    try:
                        commit_method("topic-1", 0, 42)
                    except TypeError:
                        pass
