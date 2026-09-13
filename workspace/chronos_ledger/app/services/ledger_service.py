"""Ledger-Service: SHA-256 Hashverkettung, Validierung und Speicherung."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.services.pii_masker import PIIMasker


def compute_block_hash(
    index: int,
    timestamp: str,
    tenant_id: str,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    """Berechnet deterministischen SHA-256 Hash eines Ledger-Blocks (GoBD-konform)."""
    serialized_payload = json.dumps(payload, sort_keys=True)
    raw_data = f"{index}|{timestamp}|{tenant_id}|{serialized_payload}|{prev_hash}"
    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()


class LedgerEntrySchema(BaseModel):
    index: int
    timestamp: str
    tenant_id: str
    payload: dict[str, Any]
    prev_hash: str
    current_hash: str


class LedgerService:
    """Verwaltet append-only Ledger mit kryptografischer Hash-Kette pro Mandant."""

    def __init__(self):
        # tenant_id -> list of entries
        self._chains: dict[str, list[dict[str, Any]]] = {}

    def append(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fügt einen neuen Eintrag kryptografisch gesichert an die Mandantenkette an."""
        masked_payload = PIIMasker.mask_payload(payload)
        chain = self._chains.setdefault(tenant_id, [])
        index = len(chain)
        prev_hash = chain[-1]["current_hash"] if index > 0 else "0" * 64
        timestamp = datetime.now(timezone.utc).isoformat()
        current_hash = compute_block_hash(
            index=index,
            timestamp=timestamp,
            tenant_id=tenant_id,
            payload=masked_payload,
            prev_hash=prev_hash,
        )

        entry = {
            "index": index,
            "timestamp": timestamp,
            "tenant_id": tenant_id,
            "payload": masked_payload,
            "prev_hash": prev_hash,
            "current_hash": current_hash,
        }
        chain.append(entry)
        return entry

    def get_chain(self, tenant_id: str) -> list[dict[str, Any]]:
        """Gibt die gesamte Kette für einen Mandanten zurück."""
        return list(self._chains.get(tenant_id, []))

    def verify_chain(self, tenant_id: str) -> tuple[bool, int | None]:
        """Verifiziert die Kette eines Mandanten."""
        chain = self._chains.get(tenant_id, [])
        prev_hash = "0" * 64
        for idx, entry in enumerate(chain):
            if entry["prev_hash"] != prev_hash:
                return False, idx

            expected_hash = compute_block_hash(
                index=entry["index"],
                timestamp=entry["timestamp"],
                tenant_id=entry["tenant_id"],
                payload=entry["payload"],
                prev_hash=entry["prev_hash"],
            )
            if entry["current_hash"] != expected_hash:
                return False, idx

            prev_hash = entry["current_hash"]

        return True, None


ledger_service = LedgerService()
