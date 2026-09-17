import re


class ScannerService:
    @staticmethod
    def scan_content(content: str) -> tuple[bool, str | None]:
        """
        Scans content for PII and Secrets.
        Returns (is_clean, quarantine_reason).
        """
        # Simple dummy logic for demonstration
        if re.search(r"\b\d{3}-\d{2}-\d{4}\b", content): # SSN
            return False, "PII detected: SSN"
        if re.search(r"password\s*=\s*['\"].+['\"]", content, re.IGNORECASE):
            return False, "Secret detected: password"
        if "CONFIDENTIAL" in content:
            return False, "Confidential marker detected"
        
        return True, None
