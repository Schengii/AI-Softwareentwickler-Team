
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TimeEntry
from app.schemas import TimeEntryCreate, TimeEntryRead
from app.security import get_current_user

router = APIRouter()

@router.post("/", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
async def create_time_entry(
    entry: TimeEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    new_entry = TimeEntry(**entry.dict(), user_id=current_user.id)
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    return new_entry

@router.get("/", response_model=list[TimeEntryRead])
async def get_time_entries(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Simplified query for demonstration
    return []
