from fastapi import FastAPI

app = FastAPI(title="Backend Service")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
