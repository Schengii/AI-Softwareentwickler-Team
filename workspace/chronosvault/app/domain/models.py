from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.infrastructure.database import Base

class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    states = Column(JSON, nullable=False)
    transitions = Column(JSON, nullable=False)
    
    instances = relationship("WorkflowInstance", back_populates="definition")

class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    id = Column(Integer, primary_key=True, index=True)
    definition_id = Column(Integer, ForeignKey("workflow_definitions.id"), nullable=False, index=True)
    current_state = Column(String, nullable=False)
    context_data = Column(JSON, nullable=True, default=None)
    
    definition = relationship("WorkflowDefinition", back_populates="instances")
    audit_logs = relationship("AuditLogEntry", back_populates="instance")

class AuditLogEntry(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(Integer, ForeignKey("workflow_instances.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    previous_state = Column(String, nullable=True)
    new_state = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(String, nullable=True)
    hash_value = Column(String, nullable=True)
    previous_hash = Column(String, nullable=True)
    
    instance = relationship("WorkflowInstance", back_populates="audit_logs")
