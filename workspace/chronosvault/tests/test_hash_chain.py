import pytest
import hashlib
import json
from datetime import datetime, timezone
from app.engine.hash_chain import HashChainService

def test_hash_chain_integrity():
    """Testet, ob die Hash-Kette bei Manipulation bricht."""
    service = HashChainService()
    genesis_hash = "0" * 64
    
    # Eintrag 1
    timestamp1 = datetime.now(timezone.utc)
    payload1 = {"data": "test"}
    payload_hash1 = service.compute_payload_hash(payload1)
    hash1 = service.compute_entry_hash(timestamp1, "user1", "CREATE", payload_hash1, genesis_hash)
    
    entry1 = {
        "sequence_number": 1,
        "current_hash": hash1,
        "timestamp": timestamp1,
        "actor_id": "user1",
        "action": "CREATE",
        "payload_hash": payload_hash1,
        "prev_hash": genesis_hash
    }
    
    # Eintrag 2
    timestamp2 = datetime.now(timezone.utc)
    payload_hash2 = service.compute_payload_hash({})
    hash2 = service.compute_entry_hash(timestamp2, "user2", "APPROVE", payload_hash2, hash1)
    
    entry2 = {
        "sequence_number": 2,
        "current_hash": hash2,
        "timestamp": timestamp2,
        "actor_id": "user2",
        "action": "APPROVE",
        "payload_hash": payload_hash2,
        "prev_hash": hash1
    }
    
    # Verifikation erfolgreich
    assert service.verify_chain([entry1, entry2]) is True
    
    # Manipulation
    manipulated_entry1 = entry1.copy()
    manipulated_entry1["payload_hash"] = service.compute_payload_hash({"data": "hacked"})
    
    assert service.verify_chain([manipulated_entry1, entry2]) is False
