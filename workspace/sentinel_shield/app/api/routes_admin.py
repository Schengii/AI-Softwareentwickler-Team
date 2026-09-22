from fastapi import APIRouter
from app.services.circuit_breaker import circuit_manager

router = APIRouter()

@router.post("/circuits/{service_name}/reset")
async def reset_circuit(service_name: str):
    circuit_manager.record_success(service_name)
    return {"status": "reset", "service": service_name}

@router.get("/circuits")
async def get_circuits():
    return {
        service: {
            "state": breaker.state,
            "failures": breaker.failures
        }
        for service, breaker in circuit_manager.breakers.items()
    }
