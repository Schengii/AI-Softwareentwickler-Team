"""CRUD-Operationen für Datenbank-Zugriffe."""

from sqlalchemy.orm import Session

from . import models, schemas


def get_item(db: Session, item_id: int) -> models.Item | None:
    return db.query(models.Item).filter(models.Item.id == item_id).first()


def get_items(db: Session, skip: int = 0, limit: int = 100) -> list[models.Item]:
    return db.query(models.Item).offset(skip).limit(limit).all()


def create_item(db: Session, item: schemas.ItemCreate, owner_id: int = 1) -> models.Item:
    db_item = models.Item(
        title=item.title,
        description=item.description,
        owner_id=owner_id,
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


def update_item(db: Session, item_id: int, item_update: schemas.ItemUpdate) -> models.Item | None:
    db_item = get_item(db, item_id)
    if not db_item:
        return None
    db_item.title = item_update.title
    db_item.description = item_update.description
    db.commit()
    db.refresh(db_item)
    return db_item


def delete_item(db: Session, item_id: int) -> bool:
    db_item = get_item(db, item_id)
    if not db_item:
        return False
    db.delete(db_item)
    db.commit()
    return True


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(models.User.email == email).first()
