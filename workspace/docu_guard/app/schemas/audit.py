from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    timestamp: datetime
    action: str
    payload: str
    prev_hash: str
    hash: str

    model_config = {"from_attributes": True}

class AuditVerifyResult(BaseModel):
    is_valid: bool
    message: str
