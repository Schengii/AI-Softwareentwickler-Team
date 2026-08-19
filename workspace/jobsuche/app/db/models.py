# app/db/models.py
from sqlalchemy import Column, String, Text, Integer, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.base import Base

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, index=True)          # UUID
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, nullable=False)
    salary = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    posted_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)          # UUID
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    consent_given = Column(Boolean, default=False)            # DSGVO‑Einwilligung
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Beziehung zu Bewerbungen (optional)
    applications = relationship("Application", back_populates="user")

class Application(Base):
    __tablename__ = "applications"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    cover_letter = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="applications")
    job = relationship("Job")
