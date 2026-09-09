
from pydantic import BaseModel


class SASTIssue(BaseModel):
    severity: str
    confidence: str
    file: str
    line: int
    message: str

class SASTReport(BaseModel):
    tool: str
    total_issues: int
    issues: list[SASTIssue]
    status: str | None = "success"
    message: str | None = None
