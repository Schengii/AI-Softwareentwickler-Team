from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str = Field(unique=True)

class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    description: Optional[str] = None
    user_id: int = Field(foreign_key="user.id")

sqlite_url = "sqlite:///database.db"
engine = create_engine(sqlite_url, echo=True)

def init_db():
    SQLModel.metadata.create_all(engine)

if __name__ == "__main__":
    init_db()
