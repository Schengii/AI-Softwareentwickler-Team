"""
core/rate_limiter.py – Einfacher In-Process Rate-Limiter (Sliding Window)

Begrenzt, wie oft ein Codepfad pro Zeitfenster ausgeführt werden darf. Genutzt von
core/llm_factory.py, um zu verhindern, dass viele parallele Agenten (asyncio.gather in
agents/orchestrator.py._run_agents_parallel) denselben LLM-Provider gleichzeitig anstürmen
und dessen Minutenlimit dadurch ERST auslösen – realer Fund: an einem Tag mit vielen
parallelen Läufen hingen alle Gemini-Kontingente gleichzeitig an ihrem Minutenlimit, weil
z.B. 3+ Agenten eines Fachbereichs ihre erste Anfrage praktisch zeitgleich abschickten.
core/token_guard.py.seconds_until_available() hilft REAKTIV (nachdem das Limit bereits
erreicht ist); dieser Rate-Limiter wirkt PROAKTIV davor, indem er Anfragen von Anfang an
zeitlich entzerrt, statt sie alle auf einmal loszuschicken.

Reines In-Process-Pacing (kein externer State, kein Cluster-übergreifendes Limit) – für den
Einsatzzweck hier (ein einzelner Framework-Prozess) bewusst ausreichend statt eines echten
verteilten Rate-Limiters.
"""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Sliding-Window-Rate-Limiter: erlaubt maximal `max_calls` Aufrufe pro `window_seconds`."""

    def __init__(self, max_calls: int, window_seconds: float = 60.0):
        self._max_calls = max_calls
        self._window = window_seconds
        self._call_times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Blockiert (asynchron, ohne den Event-Loop zu sperren), bis ein neuer Aufruf innerhalb
        des gleitenden Zeitfensters erlaubt ist. Wartende Aufrufer werden strikt der Reihe nach
        bedient (kein Thundering Herd beim Aufwachen), da acquire() den Lock während des
        Wartens hält.
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._call_times and now - self._call_times[0] >= self._window:
                    self._call_times.popleft()
                if len(self._call_times) < self._max_calls:
                    self._call_times.append(now)
                    return
                wait = self._window - (now - self._call_times[0])
                await asyncio.sleep(max(wait, 0.01))
