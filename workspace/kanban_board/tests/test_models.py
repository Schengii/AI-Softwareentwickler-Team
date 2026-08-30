import pytest
from models import Board, Column, Card
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

def test_card_creation(session):
    board = Board(title="Test Board")
    session.add(board)
    session.commit()
    
    col = Column(title="Todo", board_id=board.id)
    session.add(col)
    session.commit()
    
    card = Card(title="Task 1", column_id=col.id, position=1)
    session.add(card)
    session.commit()
    
    assert card.id is not None
    assert card.column_id == col.id
