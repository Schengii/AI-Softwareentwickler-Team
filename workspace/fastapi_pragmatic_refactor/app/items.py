from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict
from .database import get_db, Item as ItemModel

router = APIRouter(prefix="/items", tags=["items"])

# Pydantic Schemas
class ItemBase(BaseModel):
    title: str
    description: str | None = None

class ItemCreate(ItemBase): pass

class ItemRead(ItemBase):
    id: int
    owner_id: int
    model_config = ConfigDict(from_attributes=True)

# CRUD Logic (direkt in der Route oder in einem schlanken Service-Modul)
@router.post("/", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate, db: AsyncSession = Depends(get_db)):
    db_item = ItemModel(**item.model_attributes)
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ItemModel).filter(ItemModel.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item
