"""
tests/test_rate_limiter.py – Testet core/rate_limiter.py (proaktive Rate-Begrenzung)

Realer Fund: 3+-Mitglieder-Fachbereiche schicken über asyncio.gather ihre erste Anfrage
praktisch zeitgleich an denselben LLM-Provider los - ohne Entzerrung stürmen alle Agenten
gleichzeitig denselben Provider an und lösen dessen Minutenlimit dadurch ERST aus, statt es
organisch über die Zeit verteilt zu erreichen. RateLimiter.acquire() entzerrt das.
"""

import asyncio
import time
import unittest

from core.rate_limiter import RateLimiter


class TestRateLimiter(unittest.TestCase):
    def test_calls_within_limit_do_not_wait(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60.0)

        async def run():
            start = time.monotonic()
            for _ in range(5):
                await limiter.acquire()
            return time.monotonic() - start

        elapsed = asyncio.run(run())
        self.assertLess(elapsed, 0.5)  # keine echte Wartezeit nötig

    def test_call_beyond_limit_waits_for_window_to_free_up(self):
        limiter = RateLimiter(max_calls=2, window_seconds=0.3)

        async def run():
            start = time.monotonic()
            await limiter.acquire()
            await limiter.acquire()
            await limiter.acquire()  # 3. Aufruf muss auf das Zeitfenster warten
            return time.monotonic() - start

        elapsed = asyncio.run(run())
        self.assertGreaterEqual(elapsed, 0.25)

    def test_many_concurrent_callers_are_serialized_not_all_admitted_at_once(self):
        """Simuliert genau den realen Fund: viele parallele Agenten (asyncio.gather)
        wollen praktisch zeitgleich denselben Provider anstürmen."""
        limiter = RateLimiter(max_calls=3, window_seconds=0.3)
        admitted_times: list[float] = []

        async def caller():
            await limiter.acquire()
            admitted_times.append(time.monotonic())

        async def run():
            start = time.monotonic()
            await asyncio.gather(*[caller() for _ in range(6)])
            return start

        start = asyncio.run(run())
        # Die ersten 3 duerfen sofort rein, die letzten 3 muessen auf das naechste
        # Zeitfenster warten - nicht alle 6 gleichzeitig.
        immediate = [t for t in admitted_times if t - start < 0.1]
        delayed = [t for t in admitted_times if t - start >= 0.1]
        self.assertEqual(len(immediate), 3)
        self.assertEqual(len(delayed), 3)


if __name__ == "__main__":
    unittest.main()
