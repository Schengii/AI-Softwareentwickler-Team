import logging
import re
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class PIIMaskingFilter(logging.Filter):
    """
    Logging-Filter, der PII (IP-Adressen und sensible Header) in Log-Nachrichten maskiert.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            # Maskiere das letzte Oktett von IPv4-Adressen
            record.msg = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}', r'\g<1>***', record.msg)
            # Maskiere sensible Header (Authorization, X-API-Key)
            record.msg = re.sub(r'(?i)(authorization|x-api-key)([:=]\s*)([^\s\'",]+)', r'\1\2***', record.msg)
        return True

class PIIMaskingFormatter(logging.Formatter):
    """
    Logging-Formatter, der PII maskiert, falls der Filter nicht ausreicht.
    """
    def format(self, record: logging.LogRecord) -> str:
        original_msg = record.msg
        if isinstance(record.msg, str):
            record.msg = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}', r'\g<1>***', record.msg)
            record.msg = re.sub(r'(?i)(authorization|x-api-key)([:=]\s*)([^\s\'",]+)', r'\1\2***', record.msg)
        
        formatted = super().format(record)
        record.msg = original_msg  # Original wiederherstellen
        return formatted

class PIILoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI Middleware, die sicherstellt, dass Request-Daten sicher geloggt werden.
    """
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        # Maskierung passiert im Logger, aber wir können hier schon präventiv filtern
        safe_ip = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}', r'\g<1>***', client_ip)
        
        logger = logging.getLogger("hyperion.requests")
        logger.info(f"Incoming request from {safe_ip} to {request.url.path}")
        
        response = await call_next(request)
        return response

def setup_pii_logging() -> None:
    """
    Konfiguriert das Root-Logging mit dem PII-Masking-Filter.
    """
    logger = logging.getLogger()
    pii_filter = PIIMaskingFilter()
    
    # Füge den Filter zu allen bestehenden Handlern hinzu
    for handler in logger.handlers:
        handler.addFilter(pii_filter)
        
    # Falls keine Handler existieren, füge einen Standard-Handler mit Formatter hinzu
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = PIIMaskingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
