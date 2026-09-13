import json
import logging
import time
from typing import Any

logger = logging.getLogger("eventstream_zero.audit")
logger.setLevel(logging.INFO)

# Ensure we don't duplicate handlers if this is imported multiple times
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def log_audit_event(event_type: str, user_id: str | None, resource: str, action: str, status: str, details: dict[str, Any] | None = None) -> None:
    """
    Logs an audit event in structured JSON format.
    
    :param event_type: Type of event (e.g., 'LOGIN', 'TOKEN_REFRESH', 'ACCESS_DENIED')
    :param user_id: ID of the user (if known)
    :param resource: The resource being accessed
    :param action: The action being performed
    :param status: 'SUCCESS' or 'FAILURE'
    :param details: Additional context
    """
    event = {
        "timestamp": time.time(),
        "event_type": event_type,
        "user_id": user_id or "anonymous",
        "resource": resource,
        "action": action,
        "status": status,
        "details": details or {}
    }
    logger.info(json.dumps(event))
