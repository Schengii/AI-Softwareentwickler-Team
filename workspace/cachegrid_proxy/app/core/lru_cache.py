"""In-Memory LRU-Cache mit TTL-Verfall und Eviction-Handling."""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """Repräsentiert einen einzelnen Cache-Eintrag im Speicher oder auf Disk."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    access_count: int = 0
    last_accessed_at: float = field(default_factory=time.time)
    tags: set[str] = field(default_factory=set)

    def is_expired(self, current_time: float | None = None) -> bool:
        """Prüft, ob der Eintrag anhand des Ablaufzeitpunkts abgelaufen ist."""
        if self.expires_at is None:
            return False
        now = current_time if current_time is not None else time.time()
        return now >= self.expires_at


class MemoryLRUCache:
    """Thread-/Task-sicherer LRU-Cache im Arbeitsspeicher mit TTL-Unterstützung."""

    def __init__(
        self,
        max_items: int = 1000,
        default_ttl: float | None = 300.0,
        on_evict: Callable[[CacheEntry], Any] | None = None,
    ) -> None:
        self.max_items = max(1, max_items)
        self.default_ttl = default_ttl
        self.on_evict = on_evict
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    def get(self, key: str) -> CacheEntry | None:
        """Gibt den Cache-Eintrag zurück, falls vorhanden und nicht abgelaufen.
        
        Verschiebt den Eintrag ans Ende der LRU-Reihenfolge.
        """
        now = time.time()
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired(now):
            # Abgelaufenes Element entfernen
            self._entries.pop(key, None)
            self._misses += 1
            return None

        # LRU-Update: ans Ende verschieben
        self._entries.move_to_end(key)
        entry.access_count += 1
        entry.last_accessed_at = now
        self._hits += 1
        return entry

    def peek(self, key: str) -> CacheEntry | None:
        """Liest den Eintrag ohne Beeinflussung der LRU-Position oder Hits/Misses."""
        entry = self._entries.get(key)
        if entry and entry.is_expired():
            return None
        return entry

    def put(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | list[str] | None = None,
    ) -> tuple[CacheEntry, CacheEntry | None]:
        """Speichert einen neuen Wert oder überschreibt einen bestehenden.
        
        Gibt ein Tupel (neuer_eintrag, evicteter_eintrag) zurück.
        """
        now = time.time()
        eff_ttl = ttl if ttl is not None else self.default_ttl
        expires_at = (now + eff_ttl) if (eff_ttl is not None and eff_ttl > 0) else None

        tag_set = set(tags) if tags else set()
        new_entry = CacheEntry(
            key=key,
            value=value,
            created_at=now,
            expires_at=expires_at,
            access_count=0,
            last_accessed_at=now,
            tags=tag_set,
        )

        evicted_entry: CacheEntry | None = None

        if key in self._entries:
            self._entries.move_to_end(key)
            self._entries[key] = new_entry
            return new_entry, None

        # Prüfe Kapazitätsgrenze für Eviction
        if len(self._entries) >= self.max_items:
            # Ältestes Element (FIFO / LRU Head) herausnehmen
            _, evicted_entry = self._entries.popitem(last=False)
            self._evictions += 1
            if self.on_evict and evicted_entry:
                self.on_evict(evicted_entry)

        self._entries[key] = new_entry
        return new_entry, evicted_entry

    def delete(self, key: str) -> bool:
        """Löscht einen Eintrag aus dem In-Memory LRU."""
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def remove_expired(self) -> int:
        """Bereinigt alle abgelaufenen Einträge und gibt deren Anzahl zurück."""
        now = time.time()
        expired_keys = [k for k, v in self._entries.items() if v.is_expired(now)]
        for k in expired_keys:
            del self._entries[k]
        return len(expired_keys)

    def clear(self) -> None:
        """Leert den gesamten Memory-Cache."""
        self._entries.clear()

    def get_stats(self) -> dict[str, Any]:
        """Gibt aggregierte Metriken zum In-Memory LRU Cache zurück."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100.0) if total_requests > 0 else 0.0
        return {
            "item_count": len(self._entries),
            "max_items": self.max_items,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate_percent": round(hit_rate, 2),
        }

    def list_keys(self) -> list[str]:
        """Gibt eine Liste aller aktuellen Keys im Cache zurück."""
        now = time.time()
        return [k for k, v in self._entries.items() if not v.is_expired(now)]
