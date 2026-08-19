# app/api/gdpr.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import json
import datetime

from app.db.session import get_db
from app.db import models
from app.api.deps import get_current_user
from app.core.logger import audit_logger

router = APIRouter()

@router.get("/export", response_model=dict)
def export_user_data(
    *,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    DSGVO‑Datenexport – gibt alle personenbezogenen Daten zurück.
    """
    # Sammle Daten aus allen relevanten Tabellen
    applications = (
        db.query(models.Application)
        .filter(models.Application.user_id == user.id)
        .all()
    )
    data = {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "consent_given": user.consent_given,
            "created_at": user.created_at.isoformat(),
        },
        "applications": [
            {
                "job_id": a.job_id,
                "cover_letter": a.cover_letter,
                "submitted_at": a.submitted_at.isoformat(),
            }
            for a in applications
        ],
    }

    # Audit‑Log
    audit_logger.info(
        f"GDPR export requested",
        extra={"user_id": user.id, "timestamp": datetime.datetime.utcnow().isoformat()}
    )
    return data

@router.delete("/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_data(
    *,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    DSGVO‑Löschanfrage – löscht oder anonymisiert personenbezogene Daten.
    """
    # 1. Anonymisiere User‑Eintrag
    user.email = f"deleted-{user.id}@example.com"
    user.full_name = None
    user.hashed_password = ""
    user.is_active = False
    user.consent_given = False

    # 2. Lösche Bewerbungen (oder setze auf anonym)
    db.query(models.Application).filter(models.Application.user_id == user.id).delete()

    db.commit()

    audit_logger.info(
        "GDPR deletion performed",
        extra={"user_id": user.id, "timestamp": datetime.datetime.utcnow().isoformat()}
    )
    return None
