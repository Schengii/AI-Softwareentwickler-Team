"""Key-granularer Mutex-Lock-Manager gegen Thundering Herd (Single-Flight Pattern)."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


class KeyLockManager:
    """Verwaltet feingranulare asyncio.Lock-Instanzen pro Cache-Key.
    
    Nutzt Referenzzählung, um nicht mehr genutzte Locks sauber aus dem
    Speicher zu entfernen (Verhinderung von Memory Leaks).
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._ref_counts: dict[str, int] = {}
        # Schützt die interne Lock-Tabelle vor Race Conditions
        self._meta_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, key: str) -> AsyncGenerator[None, None]:
        """Erwirbt einen exklusiven Mutex für den angegebenen Key."""
        async with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
                self._ref_counts[key] = 0
            self._ref_counts[key] += 1
            lock = self._locks[key]

        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            async with self._meta_lock:
                self._ref_counts[key] -= 1
                if self._ref_counts[key] <= 0:
                    self._locks.pop(key, None)
                    self._ref_counts.pop(key, None)

    async def get_active_locks_count(self) -> int:
        """Gibt die Anzahl aktuell registrierter Locks zurück."""
        async with self._meta_lock:
            return len(self._locks)
