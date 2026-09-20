from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None

class ErrorEnvelope(BaseModel):
    error: ErrorDetail

class SynapseException(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

async def synapse_exception_handler(request: Request, exc: SynapseException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorEnvelope(
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details
            )
        ).model_dump(exclude_none=True)
    )

async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # No naked 500 tracebacks
    return JSONResponse(
        status_code=500,
        content=ErrorEnvelope(
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred."
            )
        ).model_dump(exclude_none=True)
    )
