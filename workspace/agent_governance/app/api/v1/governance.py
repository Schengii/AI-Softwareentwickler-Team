import uuid

from fastapi import APIRouter, HTTPException

from app.schemas.audit import AuditRequest, AuditResponse
from src.api_integration.sast_adapter import SASTAdapter

router = APIRouter()

@router.post("/run", response_model=AuditResponse)
async def run_audit(request: AuditRequest):
    """
    Startet eine Sicherheitsanalyse für das angegebene Repository.
    """
    adapter = SASTAdapter(tool="bandit")
    # In einer realen Umgebung wäre dies ein Hintergrund-Task
    try:
        report = adapter.run_analysis(request.repo_url)
        return AuditResponse(
            audit_id=str(uuid.uuid4()),
            status="completed",
            report=report.model_dump()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
