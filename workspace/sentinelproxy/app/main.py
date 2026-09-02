import httpx
from circuitbreaker import CircuitBreakerError
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient

from app.core.resilience import retry_policy, upstream_circuit

app = FastAPI(title="SentinelProxy", version="1.0.0")

ALLOWED_HOSTS = ["internal-service.local", "api.internal", "localhost", "test"]
client = AsyncClient(base_url="http://internal-service.local", timeout=5.0)

def validate_path(path: str) -> str:
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return path

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
@upstream_circuit
@retry_policy
async def proxy(path: str, request: Request, host: str = Header(default="internal-service.local")):
    if host not in ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="Forbidden Host")
    
    clean_path = validate_path(path)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
    headers["Host"] = host

    try:
        response = await client.request(
            method=request.method,
            url=f"/{clean_path}",
            headers=headers,
            content=await request.body()
        )
        return JSONResponse(content=response.json(), status_code=response.status_code)
    except CircuitBreakerError:
        return JSONResponse(content={"error": "service unavailable (circuit open)"}, status_code=503)
    except httpx.HTTPStatusError as e:
        return JSONResponse(content={"error": "upstream error"}, status_code=e.response.status_code)
    except Exception:
        raise HTTPException(status_code=502, detail="Bad Gateway")
