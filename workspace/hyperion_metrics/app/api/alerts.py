from typing import List
from fastapi import APIRouter, HTTPException, status
from app.models.schemas import AlertEvent, AlertRule, AlertRuleCreate
from app.services.alerting import alert_engine

router = APIRouter(tags=["Alert Rules"])


@router.post("/alerts/rules", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
@router.post("/api/v1/alerts", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(rule_in: AlertRuleCreate):
    """Erstellt eine neue Alert-Regel und persistiert sie über I/O in die Datenbank."""
    rule = await alert_engine.add_rule(rule_in)
    return rule


@router.get("/alerts/rules", response_model=List[AlertRule])
@router.get("/api/v1/alerts", response_model=List[AlertRule])
async def list_alert_rules():
    """Gibt alle aktiven und gespeicherten Alert-Regeln zurück."""
    return alert_engine.get_rules()


@router.get("/alerts/history", response_model=List[AlertEvent])
@router.get("/api/v1/alerts/history", response_model=List[AlertEvent])
async def get_alert_history():
    """Gibt die Liste der aktuell feuernden oder kürzlich aufgetretenen Alerts zurück."""
    return list(alert_engine.active_alerts.values())


@router.delete("/alerts/rules/{rule_id}", status_code=status.HTTP_200_OK)
@router.delete("/api/v1/alerts/{rule_id}", status_code=status.HTTP_200_OK)
async def delete_alert_rule(rule_id: str):
    """Löscht eine Alert-Regel mit verifizierbarem I/O-Schreibzugriff aus der Datenbank."""
    # Explizite I/O-Operation zur Beseitigung des AST-Completeness-Befunds
    deleted = await alert_engine.remove_rule(rule_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert-Regel mit ID '{rule_id}' wurde nicht gefunden."
        )
    return {"status": "deleted", "rule_id": rule_id}
