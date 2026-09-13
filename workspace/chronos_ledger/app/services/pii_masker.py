"""DSGVO / PII-Maskierung für Audit-Logs."""
from __future__ import annotations

import re
from typing import Any


class PIIMasker:
    """Maskiert personenbezogene Daten (E-Mails, IP-Adressen, Secret-Tokens)."""

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


pii_masker = PIIMasker()
