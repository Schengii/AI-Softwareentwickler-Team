from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import os

from app.db.session import init_db, get_async_session
from app.models.models import Task, TeamMetric
from app.schemas.schemas import (
    TaskCreate,
    TaskUpdate,
    TaskResponse,
    TeamMetricCreate,
    TeamMetricResponse,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Analytics Hub", lifespan=lifespan)

# Health Check
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# --- Task Endpoints ---
@app.post("/api/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(task: TaskCreate, db: AsyncSession = Depends(get_async_session)):
    new_task = Task(**task.model_dump())
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task

@app.get("/api/tasks", response_model=List[TaskResponse])
@app.get("/tasks", response_model=List[TaskResponse])
async def get_tasks(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Task))
    return result.scalars().all()

@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_async_session)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task

@app.put("/api/tasks/{task_id}", response_model=TaskResponse)
@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: int, task_update: TaskUpdate, db: AsyncSession = Depends(get_async_session)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    update_data = task_update.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(task, field, val)
    await db.commit()
    await db.refresh(task)
    return task

@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_async_session)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await db.delete(task)
    await db.commit()
    return None

# --- TeamMetric Endpoints ---
@app.post("/api/metrics", response_model=TeamMetricResponse, status_code=status.HTTP_201_CREATED)
@app.post("/metrics", response_model=TeamMetricResponse, status_code=status.HTTP_201_CREATED)
async def create_metric(metric: TeamMetricCreate, db: AsyncSession = Depends(get_async_session)):
    new_metric = TeamMetric(**metric.model_dump())
    db.add(new_metric)
    await db.commit()
    await db.refresh(new_metric)
    return new_metric

@app.get("/api/metrics", response_model=List[TeamMetricResponse])
@app.get("/metrics", response_model=List[TeamMetricResponse])
async def get_metrics(db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(TeamMetric))
    return result.scalars().all()

@app.get("/api/metrics/{metric_id}", response_model=TeamMetricResponse)
@app.get("/metrics/{metric_id}", response_model=TeamMetricResponse)
async def get_metric(metric_id: int, db: AsyncSession = Depends(get_async_session)):
    metric = await db.get(TeamMetric, metric_id)
    if not metric:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found")
    return metric

@app.delete("/api/metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
@app.delete("/metrics/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(metric_id: int, db: AsyncSession = Depends(get_async_session)):
    metric = await db.get(TeamMetric, metric_id)
    if not metric:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found")
    await db.delete(metric)
    await db.commit()
    return None

# Mount Static Files (Frontend)
if not os.path.exists("public"):
    os.makedirs("public")
app.mount("/", StaticFiles(directory="public", html=True), name="public")
