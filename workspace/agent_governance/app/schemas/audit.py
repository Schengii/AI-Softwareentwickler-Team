from pydantic import BaseModel


class AuditRequest(BaseModel):
    repo_url: str
    scan_type: str

class AuditResponse(BaseModel):
    audit_id: str
    status: str
    report: dict | None = None
