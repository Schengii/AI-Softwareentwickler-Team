import json
import logging
from typing import Any

logger = logging.getLogger("nexus_mesh")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def log_audit(event: str, details: dict[str, Any]):
    log_entry = {
        "event": event,
        **details
    }
    logger.info(json.dumps(log_entry))
