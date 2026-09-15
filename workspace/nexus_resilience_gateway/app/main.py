import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="nexus_resilience_gateway")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-Tenant-ID", "X-Signature", "X-Timestamp", "X-Nonce", "Content-Type", "Authorization"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "nexus_resilience_gateway"}
