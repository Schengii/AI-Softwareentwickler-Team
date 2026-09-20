"""CacheGridEngine: Fassade für hierarchisches Caching, Mutex-Locking und Tagging."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.concurrency import KeyLockManager
from app.core.config import Settings, get_settings
from app.core.disk_storage import DiskTierStorage
from app.core.lru_cache import CacheEntry, MemoryLRUCache
from app.core.tag_index import TagIndex
from app.core.write_behind import WriteBehindWorker

logger = logging.getLogger("cachegrid.engine")


class CacheGridEngine:
    """Zentrale Cache-Engine, die RAM-, Disk-, Mutex- und Tag-Komponenten orchestriert."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.lock_manager = KeyLockManager()
        self.tag_index = TagIndex()
        
        self.disk_storage = DiskTierStorage(storage_dir=self.settings.DISK_STORAGE_PATH)
        
        # Callback bei In-Memory Eviction: Evictetes Element auf Disk auslagern (Tiering)
        def _on_memory_evict(evicted: CacheEntry) -> None:
            if self.settings.ENABLE_DISK_TIER and not evicted.is_expired():
                # Synchrone oder geplante Auslagerung
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.disk_storage.save(evicted))
                except RuntimeError:
                    pass

        self.memory_cache = MemoryLRUCache(
            max_items=self.settings.MEMORY_MAX_ITEMS,
            default_ttl=self.settings.DEFAULT_TTL_SECONDS,
            on_evict=_on_memory_evict,
        )

        self.write_behind_worker = WriteBehindWorker(
            disk_storage=self.disk_storage,
            flush_interval=self.settings.WRITE_BEHIND_FLUSH_INTERVAL,
            batch_size=self.settings.WRITE_BEHIND_BATCH_SIZE,
        )
        self._read_through_calls: int = 0
        self._thundering_herd_prevention_hits: int = 0

    async def start(self) -> None:
        """Startet Hintergrundprozesse der CacheGridEngine."""
        if self.settings.ENABLE_WRITE_BEHIND:
            self.write_behind_worker.start()
        logger.info("CacheGridEngine erfolgreich initialisiert.")

    async def stop(self) -> None:
        """Beendet Hintergrundprozesse sauber."""
        if self.settings.ENABLE_WRITE_BEHIND:
            await self.write_behind_worker.stop()
        logger.info("CacheGridEngine heruntergefahren.")

    async def get(self, key: str) -> Any | None:
        """Liest einen Wert aus Tier 1 (RAM) oder Tier 2 (Disk).
        
        Bei Disk-Hit wird das Element automatisch in Tier 1 zurückbefördert (Promotion).
        """
        # 1. Tier 1 (RAM)
        entry = self.memory_cache.get(key)
        if entry is not None:
            return entry.value

        # 2. Tier 2 (Disk)
        if self.settings.ENABLE_DISK_TIER:
            disk_entry = await self.disk_storage.load(key)
            if disk_entry is not None:
                # Promotion in Tier 1
                ttl_remaining = (disk_entry.expires_at - time.time()) if disk_entry.expires_at else None
                if ttl_remaining is None or ttl_remaining > 0:
                    self.memory_cache.put(
                        key=disk_entry.key,
                        value=disk_entry.value,
                        ttl=ttl_remaining,
                        tags=disk_entry.tags,
                    )
                    self.tag_index.associate(disk_entry.key, disk_entry.tags)
                    return disk_entry.value
        return None

    async def get_entry(self, key: str) -> CacheEntry | None:
        """Gibt das vollständige CacheEntry-Objekt für Inspektionen zurück."""
        entry = self.memory_cache.peek(key)
        if entry is not None:
            return entry
        if self.settings.ENABLE_DISK_TIER:
            return await self.disk_storage.load(key)
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: list[str] | set[str] | None = None,
        write_behind: bool | None = None,
    ) -> CacheEntry:
        """Speichert einen Eintrag im RAM und optional auf Disk (Write-Behind)."""
        tag_set = set(tags) if tags else set()
        entry, _ = self.memory_cache.put(key, value, ttl=ttl, tags=tag_set)
        
        if tag_set:
            self.tag_index.associate(key, tag_set)

        use_write_behind = (
            write_behind if write_behind is not None else self.settings.ENABLE_WRITE_BEHIND
        )

        if self.settings.ENABLE_DISK_TIER:
            if use_write_behind:
                await self.write_behind_worker.enqueue(entry)
            else:
                await self.disk_storage.save(entry)

        return entry

    async def get_or_compute(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl: float | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        """Read-Through mit Single-Flight Mutex-Locking gegen Thundering Herd."""
        self._read_through_calls += 1

        # 1. Erste Schnellprüfung vor dem Lock (Fast-Path)
        val = await self.get(key)
        if val is not None:
            return val

        # 2. Mutex-Lock für diesen spezifischen Key erwerben
        async with self.lock_manager.acquire(key):
            # Double-Checked Locking: Ein anderer Task könnte die Daten geladen haben
            val_after_lock = await self.get(key)
            if val_after_lock is not None:
                self._thundering_herd_prevention_hits += 1
                return val_after_lock

            # Cache Miss bleibt bestehen: Upstream-Loader aufrufen
            computed_value = await loader()
            await self.set(key=key, value=computed_value, ttl=ttl, tags=tags)
            return computed_value

    async def delete(self, key: str) -> bool:
        """Löscht einen Key aus RAM, Disk und dem Tag-Index."""
        mem_deleted = self.memory_cache.delete(key)
        disk_deleted = False
        if self.settings.ENABLE_DISK_TIER:
            disk_deleted = await self.disk_storage.delete(key)
        self.tag_index.disassociate_key(key)
        return mem_deleted or disk_deleted

    async def invalidate_by_tag(self, tag: str) -> list[str]:
        """Invalidiert selektiv alle Keys, die mit einem bestimmten Tag markiert sind."""
        keys = self.tag_index.get_keys_for_tag(tag)
        invalidated_keys = []
        for key in keys:
            deleted = await self.delete(key)
            if deleted:
                invalidated_keys.append(key)
        return invalidated_keys

    async def invalidate_by_tags(self, tags: list[str], mode: str = "any") -> list[str]:
        """Invalidiert Keys basierend auf einer Liste von Tags ('any' oder 'all')."""
        if not tags:
            return []
        
        target_keys: set[str] = set()
        if mode == "all":
            for i, tag in enumerate(tags):
                tag_keys = self.tag_index.get_keys_for_tag(tag)
                if i == 0:
                    target_keys = tag_keys
                else:
                    target_keys = target_keys.intersection(tag_keys)
        else:
            for tag in tags:
                target_keys.update(self.tag_index.get_keys_for_tag(tag))

        invalidated_keys = []
        for key in target_keys:
            deleted = await self.delete(key)
            if deleted:
                invalidated_keys.append(key)
        return invalidated_keys

    async def clear_all(self) -> None:
        """Leert alle Cache-Tiers und Indizes vollständig."""
        self.memory_cache.clear()
        self.tag_index.clear()
        if self.settings.ENABLE_DISK_TIER:
            await self.disk_storage.clear()

    async def inspect_key(self, key: str) -> dict[str, Any] | None:
        """Gibt detaillierte Metadaten zu einem Schlüssel zurück."""
        mem_entry = self.memory_cache.peek(key)
        tier = "memory" if mem_entry else "disk"
        entry = mem_entry

        if entry is None and self.settings.ENABLE_DISK_TIER:
            entry = await self.disk_storage.load(key)

        if entry is None:
            return None

        now = time.time()
        ttl_remaining = max(0.0, entry.expires_at - now) if entry.expires_at else None

        return {
            "key": entry.key,
            "value": entry.value,
            "tier": tier,
            "created_at": entry.created_at,
            "expires_at": entry.expires_at,
            "ttl_remaining_seconds": round(ttl_remaining, 2) if ttl_remaining is not None else None,
            "access_count": entry.access_count,
            "last_accessed_at": entry.last_accessed_at,
            "tags": list(entry.tags),
            "is_expired": entry.is_expired(now),
        }

    async def get_overall_stats(self) -> dict[str, Any]:
        """Liefert aggregierte Gesamtkennzahlen über alle Cache-Subsysteme."""
        mem_stats = self.memory_cache.get_stats()
        disk_stats = self.disk_storage.get_stats() if self.settings.ENABLE_DISK_TIER else {}
        wb_stats = self.write_behind_worker.get_stats() if self.settings.ENABLE_WRITE_BEHIND else {}
        active_locks = await self.lock_manager.get_active_locks_count()

        total_hits = mem_stats["hits"] + disk_stats.get("disk_hits", 0)
        total_misses = mem_stats["misses"]
        total_requests = total_hits + total_misses
        overall_hit_rate = (total_hits / total_requests * 100.0) if total_requests > 0 else 0.0

        return {
            "status": "online",
            "overall_hit_rate_percent": round(overall_hit_rate, 2),
            "read_through_requests": self._read_through_calls,
            "thundering_herd_prevention_hits": self._thundering_herd_prevention_hits,
            "active_concurrency_locks": active_locks,
            "tags_count": len(self.tag_index.get_all_tags()),
            "memory_tier": mem_stats,
            "disk_tier": disk_stats,
            "write_behind": wb_stats,
        }


# Globale Instanz
_cache_engine: CacheGridEngine | None = None


def get_cache_engine() -> CacheGridEngine:
    """Liefert das Singleton der CacheGridEngine."""
    global _cache_engine
    if _cache_engine is None:
        _cache_engine = CacheGridEngine()
    return _cache_engine
