from sqlmodel import create_engine, SQLModel, Session

sqlite_url = "sqlite:///./kanban.db"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
