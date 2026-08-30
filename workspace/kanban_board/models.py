from typing import List, Optional
from sqlmodel import SQLModel, Field, Relationship, create_engine, Session

class Board(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    columns: List["Column"] = Relationship(back_populates="board")

class Column(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    board_id: int = Field(foreign_key="board.id")
    board: Board = Relationship(back_populates="columns")
    cards: List["Card"] = Relationship(back_populates="column")

class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    column_id: int = Field(foreign_key="column.id")
    column: Column = Relationship(back_populates="cards")
    position: int # Für Drag-and-Drop Sortierung
