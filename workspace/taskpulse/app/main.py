import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import database, models, schemas
from .core.config import settings

app = FastAPI(title="TaskPulse API")

# Security Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://cdn.tailwindcss.com;"
    return response

# DB Initialisierung
database.init_db()

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def cleanup_old_status():
    db = database.SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        db.query(models.EndpointStatus).filter(models.EndpointStatus.timestamp < cutoff).delete()
        db.commit()
    finally:
        db.close()

async def check_endpoint(url: str):
    parsed = urlparse(url)
    if parsed.netloc not in settings.ALLOWED_CHECK_HOSTS:
        return
        
    async with httpx.AsyncClient() as client:
        try:
            start = asyncio.get_event_loop().time()
            response = await client.get(url)
            end = asyncio.get_event_loop().time()
            
            db = database.SessionLocal()
            status = models.EndpointStatus(
                url=url,
                status_code=response.status_code,
                response_time=end - start
            )
            db.add(status)
            db.commit()
            db.close()
        except Exception as e:
            print(f"Error checking {url}: {e}")

@app.on_event("startup")
async def startup_event():
    # Schedule cleanup job
    pass

@app.get("/tasks", response_model=list[schemas.TaskResponse])
def read_tasks(db: Session = Depends(get_db)):
    return db.query(models.Task).all()

@app.post("/tasks", response_model=schemas.TaskResponse)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    db_task = models.Task(name=task.name)
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

@app.get("/status", response_model=list[schemas.EndpointStatusResponse])
def read_status(db: Session = Depends(get_db)):
    return db.query(models.EndpointStatus).all()

@app.post("/status/check")
async def trigger_check(url: str, background_tasks: BackgroundTasks):
    parsed = urlparse(url)
    if parsed.netloc not in settings.ALLOWED_CHECK_HOSTS:
        raise HTTPException(status_code=400, detail="URL domain not allowed")
    background_tasks.add_task(check_endpoint, url)
    background_tasks.add_task(cleanup_old_status)
    return {"message": "Check initiated"}
