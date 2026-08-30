import enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
from sqlalchemy import Column, Integer, String, Enum, Text, DateTime, func
from app.db.database import Base

class TaskStatus(str, enum.Enum):
    TODO = "Todo"
    IN_PROGRESS = "In Progress"
    REVIEW = "Review"
    DONE = "Done"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.TODO)
    assignee = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# Pydantic Schemas mit strenger Eingabevalidierung
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Titel des Tasks")
    description: Optional[str] = Field(None, max_length=2000, description="Beschreibung")
    status: TaskStatus = Field(default=TaskStatus.TODO, description="Status des Tasks")
    assignee: Optional[str] = Field(None, max_length=255, description="Zuweisung")

    @validator("title", "assignee", "description", pre=True)
    def sanitize_strings(cls, v):
        if isinstance(v, str):
            v = v.strip()
            # Einfaches XSS Sanitizing
            v = v.replace("<script>", "").replace("</script>", "")
        return v

class TaskCreate(TaskBase):
    pass

class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[TaskStatus] = None
    assignee: Optional[str] = Field(None, max_length=255)

class TaskRead(TaskBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True
