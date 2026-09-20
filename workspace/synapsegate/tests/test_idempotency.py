import asyncio

import pytest

from app.core.idempotency import IdempotencyEngine


@pytest.mark.asyncio
async def test_idempotency_concurrency():
    """Concurrency-Test: Prüft, ob parallele Requests mit gleichem Key korrekt blockiert werden."""
    engine = IdempotencyEngine()
    key = "test-key"
    
    async def task():
        return await engine.acquire(key)

    # Starte 10 parallele Versuche
    results = await asyncio.gather(*[task() for _ in range(10)], return_exceptions=True)
    
    # Nur einer sollte True sein (erfolgreich gesperrt), die anderen False oder Exception
    successes = [r for r in results if r is True]
    assert len(successes) == 1
    
    # Cleanup
    await engine.release(key)
    assert await engine.acquire(key) is True
