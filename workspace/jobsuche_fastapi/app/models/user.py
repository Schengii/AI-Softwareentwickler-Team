# app/models/user.py
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

class UserBase(SQLModel):
    email: str = Field(index=True, nullable=False, unique=True)
    full_name: Optional[str] = None
    is_active: bool = Field(default=True)
    is_admin: bool = Field(default=False)

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str
    # Beziehungen
    profile: Optional["Profile"] = Relationship(back_populates="owner")
    applications: List["Application"] = Relationship(back_populates="applicant")
    saved_jobs: List["Job"] = Relationship(back_populates="saved_by", link_model="SavedJobLink")

class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    location: Optional[str] = None
    desired_salary: Optional[int] = None
    skills: Optional[str] = None   # CSV‑Liste (einfach für Demo)
    resume_path: Optional[str] = None

    owner: User = Relationship(back_populates="profile")

class SavedJobLink(SQLModel, table=True):
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    job_id: int = Field(foreign_key="job.id", primary_key=True)
