import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, ForeignKey, Index

# USE_SQLITE Flag gemäß Best Practices
USE_SQLITE = os.getenv("USE_SQLITE", "True") == "True"
DATABASE_URL = "sqlite+aiosqlite:///./tasks.db" if USE_SQLITE else os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # email bleibt optional: schemas.UserCreate (Registrierung) fragt bewusst nur
    # username/password ab, kein E-Mail-Feld - siehe auth.py/main.py für den Login-Flow.
    email: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        Index("idx_task_status", "status"),
        Index("idx_task_user_id", "user_id"),
    )

async def get_db():
    async with async_session() as session:
        yield session
