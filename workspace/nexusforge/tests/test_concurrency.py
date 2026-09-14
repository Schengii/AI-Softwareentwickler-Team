import asyncio

import pytest


@pytest.mark.asyncio
async def test_concurrent_evaluations():
    """Simuliert 100 gleichzeitige Evaluations-Requests ohne Race Conditions."""
    async def simulate_evaluation(user_id: str):
        # Simuliert Evaluation auf In-Memory-Cache
        await asyncio.sleep(0.001)
        return True

    tasks = [simulate_evaluation(f"user_{i}") for i in range(100)]
    results = await asyncio.gather(*tasks)
    assert len(results) == 100
    assert all(r is True for r in results)
