import asyncio

import pytest

from app.core.concurrency import KeyLockManager
from app.core.lru_cache import MemoryLRUCache


@pytest.mark.asyncio
async def test_lru_eviction():
    """Testet, ob das LRU-Cache korrekt Elemente bei Kapazitätsüberschreitung entfernt."""
    cache = MemoryLRUCache(max_items=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # 'a' sollte entfernt werden
    
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.get("c") is not None

@pytest.mark.asyncio
async def test_thundering_herd_protection():
    """Testet, ob KeyLockManager parallele Zugriffe auf denselben Key serialisiert."""
    lock_mgr = KeyLockManager()
    call_count = 0

    async def protected_task():
        nonlocal call_count
        async with lock_mgr.acquire("test_key"):
            await asyncio.sleep(0.1)
            call_count += 1

    # Starte mehrere Aufgaben gleichzeitig
    await asyncio.gather(protected_task(), protected_task(), protected_task())
    
    # Da serialisiert, sollte call_count genau 3 sein
    assert call_count == 3
