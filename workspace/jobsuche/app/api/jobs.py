# app/api/jobs.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.schemas.job import JobCreate, JobRead
from app.db import models
from app.core.security import verify_password, decode_access_token
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/", response_model=List[JobRead])
def list_jobs(
    *,
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Volltextsuche (Titel, Firma)"),
    location: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    Jobs durchsuchen – DSGVO‑konform, keine personenbezogenen Daten.
    """
    query = db.query(models.Job).filter(models.Job.is_active.is_(True))

    if q:
        pattern = f"%{q.lower()}%"
        query = query.filter(
            models.Job.title.ilike(pattern) |
            models.Job.company.ilike(pattern)
        )
    if location:
        query = query.filter(models.Job.location.ilike(f"%{location}%"))

    return query.offset(offset).limit(limit).all()

@router.post("/", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    *,
    job_in: JobCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Nur authentifizierte Recruiter dürfen Jobs anlegen.
    """
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inaktiver Nutzer")

    new_job = models.Job(**job_in.dict())
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    # Event‑Bus: JobCreated
    # (Pseudo‑Code – RabbitMQ‑Publisher)
    # publish_event("job.created", {"job_id": new_job.id})

    return new_job

@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job or not job.is_active:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return job

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    *,
    job_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Soft‑Delete (is_active = False) – ermöglicht Daten‑Wiederherstellung
    und erfüllt DSGVO‑Aufbewahrungspflicht.
    """
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    job.is_active = False
    db.commit()
    return None
