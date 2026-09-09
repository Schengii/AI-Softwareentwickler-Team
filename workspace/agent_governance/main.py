from app.api.v1.governance import router as governance_router

app.include_router(governance_router, prefix="/api/v1/audit", tags=["governance"])
