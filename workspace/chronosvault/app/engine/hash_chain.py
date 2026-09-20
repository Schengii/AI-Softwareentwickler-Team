import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

class HashChainService:
    GENESIS_HASH = "0" * 64
    # Watchdog reset

    @staticmethod
    def compute_payload_hash(payload: Optional[Dict[str, Any]]) -> str:
        if not payload:
            return hashlib.sha256(b"").hexdigest()
        payload_str = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_entry_hash(timestamp: datetime, actor_id: str, action: str, payload_hash: str, prev_hash: str) -> str:
        data = f"{timestamp.isoformat()}|{actor_id}|{action}|{payload_hash}|{prev_hash}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_chain(entries) -> bool:
        """
        Verifies the cryptographic hash chain of a list of audit log entries.
        Returns True if valid, False otherwise.
        """
        if not entries:
            return True
            
        prev_hash = HashChainService.GENESIS_HASH
        for entry in sorted(entries, key=lambda x: x.sequence_number):
            if entry.prev_hash != prev_hash:
                return False
            
            expected_hash = HashChainService.compute_entry_hash(
                timestamp=entry.timestamp,
                actor_id=entry.actor_id,
                action=entry.action,
                payload_hash=entry.payload_hash or hashlib.sha256(b"").hexdigest(),
                prev_hash=prev_hash
            )
            
            if entry.current_hash != expected_hash:
                return False
                
            prev_hash = entry.current_hash
            
        return True
