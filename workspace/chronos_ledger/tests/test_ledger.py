"""ChronosLedger Testsuite: Kryptografische Hashverkettung, Manipulationserkennung,
Auth-Validierung (HMAC-SHA256), PII-Maskierung und Anomalie-Erkennung.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from app.services.anomaly_detector import AnomalyDetector, IngestionMetric

# ============================================================================
# 1. Kryptografische Verkettung (SHA-256 Hashverkettung & Manipulationserkennung)
# ============================================================================

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


class LedgerChainVerifier:
    """Verifiziert die mathematische Integrität und Manipulationssicherheit der Hash-Kette."""

    @staticmethod
    def verify_chain(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
        """Gibt (True, None) zurück bei intakter Kette, sonst (False, manipulierter_index)."""
        prev_hash = "0" * 64
        for idx, entry in enumerate(entries):
            # Prüfe ob der referenzierte Vorgaenger-Hash stimmt
            if entry["prev_hash"] != prev_hash:
                return False, idx

            # Berechne den aktuellen Hash nach
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


def test_cryptographic_chain_integrity():
    """Testet, dass eine valide SHA-256 Hashverkettung korrekt als unverfälscht verifiziert wird."""
    entries = []
    prev_hash = "0" * 64

    for i in range(5):
        payload = {"action": "LOGIN", "user_id": f"usr_{i}"}
        ts = f"2025-01-01T10:0{i}:00Z"
        current_hash = compute_block_hash(
            index=i,
            timestamp=ts,
            tenant_id="tenant_alpha",
            payload=payload,
            prev_hash=prev_hash,
        )
        entries.append({
            "index": i,
            "timestamp": ts,
            "tenant_id": "tenant_alpha",
            "payload": payload,
            "prev_hash": prev_hash,
            "current_hash": current_hash,
        })
        prev_hash = current_hash

    is_valid, corrupted_idx = LedgerChainVerifier.verify_chain(entries)
    assert is_valid is True
    assert corrupted_idx is None


def test_cryptographic_tamper_detection_payload_modification():
    """Manipulationserkennung: Veränderung des Payloads in der Historie bricht die Verifikation sofort."""
    entries = []
    prev_hash = "0" * 64

    for i in range(4):
        payload = {"amount": 100 * (i + 1), "currency": "EUR"}
        ts = f"2025-01-01T12:0{i}:00Z"
        c_hash = compute_block_hash(i, ts, "tenant_finance", payload, prev_hash)
        entries.append({
            "index": i,
            "timestamp": ts,
            "tenant_id": "tenant_finance",
            "payload": payload,
            "prev_hash": prev_hash,
            "current_hash": c_hash,
        })
        prev_hash = c_hash

    # Manipulation an Block 2 (Index 1): Betrag heimlich ändern
    entries[1]["payload"] = {"amount": 999999, "currency": "EUR"}

    is_valid, corrupted_idx = LedgerChainVerifier.verify_chain(entries)
    assert is_valid is False
    assert corrupted_idx == 1


def test_cryptographic_tamper_detection_chain_break():
    """Manipulationserkennung: Löschen oder Austauschen eines Eintrags zerstört die Verkettung."""
    entries = []
    prev_hash = "0" * 64

    for i in range(3):
        payload = {"event": f"audit_{i}"}
        ts = f"2025-01-01T12:0{i}:00Z"
        c_hash = compute_block_hash(i, ts, "tenant_ops", payload, prev_hash)
        entries.append({
            "index": i,
            "timestamp": ts,
            "tenant_id": "tenant_ops",
            "payload": payload,
            "prev_hash": prev_hash,
            "current_hash": c_hash,
        })
        prev_hash = c_hash

    # Eintrag an Index 1 fälschen mit neuem prev_hash
    entries[2]["prev_hash"] = "invalid_hash_value" * 4

    is_valid, corrupted_idx = LedgerChainVerifier.verify_chain(entries)
    assert is_valid is False
    assert corrupted_idx == 2


# ============================================================================
# 2. Sicherheit & Timing-sichere HMAC-Validierung
# ============================================================================

def timing_safe_hmac_verify(secret: bytes, message: bytes, signature_hex: str) -> bool:
    """Timing-sichere Validierung von HMAC-SHA256 Signaturen."""
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex)


def test_hmac_timing_safe_validation():
    """Prüft korrekte Signatur-Akzeptanz und deterministische Ablehnung unberechtigter Signaturen."""
    secret = b"super-secret-tenant-key-12345"
    payload = b'{"log": "incident_detected", "severity": "CRITICAL"}'
    valid_signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()

    # Valide Signatur
    assert timing_safe_hmac_verify(secret, payload, valid_signature) is True

    # Manipulierter Payload -> Ablehnung
    tampered_payload = b'{"log": "incident_detected", "severity": "LOW"}'
    assert timing_safe_hmac_verify(secret, tampered_payload, valid_signature) is False

    # Falsches Secret -> Ablehnung
    wrong_secret = b"attacker-key-99999"
    assert timing_safe_hmac_verify(wrong_secret, payload, valid_signature) is False


# ============================================================================
# 3. PII-Maskierung (DSGVO-Compliance)
# ============================================================================

class PIIMasker:
    """Maskiert E-Mail-Adressen, IPv4-Adressen und Secret-Tokens in Log-Payloads."""

    EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    IPV4_REGEX = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    TOKEN_REGEX = re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]+)|(api_key=[A-Za-z0-9_\-]+)")

    @classmethod
    def mask_text(cls, text: str) -> str:
        text = cls.EMAIL_REGEX.sub("[EMAIL_PSEUDONYMIZED]", text)
        text = cls.IPV4_REGEX.sub("[IP_MASKED]", text)
        text = cls.TOKEN_REGEX.sub("[SECRET_MASKED]", text)
        return text

    @classmethod
    def mask_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: cls.mask_payload(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.mask_payload(item) for item in data]
        elif isinstance(data, str):
            return cls.mask_text(data)
        return data


def test_pii_masking_emails_ips_and_secrets():
    """Testet die automatische Pseudonymisierung von personenbezogenen Daten im Audit-Log."""
    raw_payload = {
        "user_email": "max.mustermann@example.com",
        "client_ip": "192.168.1.105",
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
        "details": {
            "contact": "support@service.de",
            "gateway": "10.0.0.1",
            "nested_list": ["admin@company.com", "token api_key=superSecretKey42"],
        },
    }

    masked = PIIMasker.mask_payload(raw_payload)

    assert masked["user_email"] == "[EMAIL_PSEUDONYMIZED]"
    assert masked["client_ip"] == "[IP_MASKED]"
    assert masked["auth_header"] == "[SECRET_MASKED]"
    assert masked["details"]["contact"] == "[EMAIL_PSEUDONYMIZED]"
    assert masked["details"]["gateway"] == "[IP_MASKED]"
    assert masked["details"]["nested_list"][0] == "[EMAIL_PSEUDONYMIZED]"
    assert masked["details"]["nested_list"][1] == "token [SECRET_MASKED]"


# ============================================================================
# 4. Anomalie-Erkennung (Z-Score Algorithmus)
# ============================================================================

def test_anomaly_detector_baseline_and_outlier_detection():
    """Testet statistische Ausreißer-Erkennung via Z-Score bei plötzlichen Ingestion-Peaks."""
    detector = AnomalyDetector(window_size=20, z_score_threshold=2.5)

    # 1. Normale Baseline einspeisen (um 100 RPS)
    for i in range(25):
        detector.record_metric(IngestionMetric(timestamp=1700000000.0 + i, request_count=100.0))

    normal_metric = IngestionMetric(timestamp=1700000026.0, request_count=105.0)
    is_anomaly, score = detector.check_anomaly(normal_metric)
    assert is_anomaly is False
    assert score < 2.5

    # 2. Plötzlicher Spike (z.B. Brute-Force / DoS Angriff mit 10.000 RPS)
    spike_metric = IngestionMetric(timestamp=1700000027.0, request_count=10000.0)
    is_anomaly, score = detector.check_anomaly(spike_metric)
    assert is_anomaly is True
    assert score >= 2.5
