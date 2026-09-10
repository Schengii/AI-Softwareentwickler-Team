from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class AuditLog(Base):
    """
    Repräsentiert ein Audit-Log-Ereignis im System.

    Attributes:
        id (int): Eindeutiger Primärschlüssel des Logs.
        timestamp (datetime): UTC-Zeitstempel der Erstellung.
        user_id (str): ID des Benutzers, der die Aktion ausgelöst hat.
        action (str): Die durchgeführte Aktion (z.B. 'LOGIN', 'DELETE').
        resource (str): Die betroffene Ressource.
        status (str): Status der Aktion (z.B. 'SUCCESS', 'FAILED').
        metadata_json (dict): Zusätzliche Kontextdaten als JSON-Payload.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id = Column(String, index=True)
    action = Column(String, index=True)
    resource = Column(String)
    status = Column(String)
    metadata_json = Column(JSON, nullable=True)
