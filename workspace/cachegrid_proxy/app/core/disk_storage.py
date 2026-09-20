"""Tier 2: Disk-Storage Persistenzschicht für ausgelagerte Cache-Einträge."""

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.core.lru_cache import CacheEntry


class DiskTierStorage:
    """Verwaltet persistenten Cache-Speicher auf der Festplatte."""

    def __init__(self, storage_dir: str = "./data/cache_disk") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._disk_hits: int = 0
        self._disk_misses: int = 0
        self._disk_writes: int = 0

    def _get_file_path(self, key: str) -> Path:
        """Erzeugt einen sicheren Dateipfad basierend auf dem Key-Hash."""
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.storage_dir / f"{key_hash}.cache.json"

    def _serialize_entry(self, entry: CacheEntry) -> str:
        data = {
            "key": entry.key,
            "value": entry.value,
            "created_at": entry.created_at,
            "expires_at": entry.expires_at,
            "access_count": entry.access_count,
            "last_accessed_at": entry.last_accessed_at,
            "tags": list(entry.tags),
        }
        return json.dumps(data, ensure_ascii=False)

    def _deserialize_entry(self, raw_json: str) -> CacheEntry:
        data = json.loads(raw_json)
        return CacheEntry(
            key=data["key"],
            value=data["value"],
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            access_count=data.get("access_count", 0),
            last_accessed_at=data.get("last_accessed_at", time.time()),
            tags=set(data.get("tags", [])),
        )

    def _sync_save(self, entry: CacheEntry) -> None:
        file_path = self._get_file_path(entry.key)
        content = self._serialize_entry(entry)
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        tmp_path.replace(file_path)
        self._disk_writes += 1

    def _sync_load(self, key: str) -> CacheEntry | None:
        file_path = self._get_file_path(key)
        if not file_path.exists():
            self._disk_misses += 1
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            entry = self._deserialize_entry(content)
            if entry.is_expired():
                file_path.unlink(missing_ok=True)
                self._disk_misses += 1
                return None
            self._disk_hits += 1
            return entry
        except (json.JSONDecodeError, OSError):
            file_path.unlink(missing_ok=True)
            self._disk_misses += 1
            return None

    def _sync_delete(self, key: str) -> bool:
        file_path = self._get_file_path(key)
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except OSError:
                return False
        return False

    def _sync_clear(self) -> None:
        for p in self.storage_dir.glob("*.cache.json"):
            try:
                p.unlink()
            except OSError:
                pass

    def _sync_list_keys(self) -> list[str]:
        keys = []
        now = time.time()
        for p in self.storage_dir.glob("*.cache.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                exp = data.get("expires_at")
                if exp is None or now < exp:
                    keys.append(data["key"])
            except (json.JSONDecodeError, OSError):
                continue
        return keys

    async def save(self, entry: CacheEntry) -> None:
        """Speichert einen Eintrag asynchron auf Festplatte."""
        await asyncio.to_thread(self._sync_save, entry)

    async def save_batch(self, entries: list[CacheEntry]) -> None:
        """Speichert eine Liste von Einträgen gebündelt auf Festplatte."""
        def _batch():
            for e in entries:
                self._sync_save(e)
        await asyncio.to_thread(_batch)

    async def load(self, key: str) -> CacheEntry | None:
        """Lädt einen Eintrag asynchron von Festplatte."""
        return await asyncio.to_thread(self._sync_load, key)

    async def delete(self, key: str) -> bool:
        """Löscht einen Eintrag asynchron von Festplatte."""
        return await asyncio.to_thread(self._sync_delete, key)

    async def clear(self) -> None:
        """Löscht alle gespeicherten Cache-Dateien."""
        await asyncio.to_thread(self._sync_clear)

    async def list_keys(self) -> list[str]:
        """Listet alle nicht abgelaufenen Keys auf Disk auf."""
        return await asyncio.to_thread(self._sync_list_keys)

    def get_stats(self) -> dict[str, Any]:
        """Gibt Disk-Metriken zurück."""
        file_count = len(list(self.storage_dir.glob("*.cache.json")))
        return {
            "disk_files": file_count,
            "disk_writes": self._disk_writes,
            "disk_hits": self._disk_hits,
            "disk_misses": self._disk_misses,
            "storage_path": str(self.storage_dir),
        }
