from fastapi import FastAPI, HTTPException, Depends
from sqlmodel import Session, select
from models import Board, Column, Card
from database import get_session

app = FastAPI()

@app.post("/boards/", response_model=Board)
def create_board(board: Board, session: Session = Depends(get_session)):
    session.add(board)
    session.commit()
    session.refresh(board)
    return board

@app.patch("/cards/{card_id}/move")
def move_card(card_id: int, new_column_id: int, new_position: int, session: Session = Depends(get_session)):
    card = session.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    card.column_id = new_column_id
    card.position = new_position
    session.commit()
    return {"message": "Card moved successfully"}
