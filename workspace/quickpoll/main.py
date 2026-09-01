from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from models import AsyncSessionLocal, Poll, Option, Vote
from connection_manager import manager
from pydantic import ValidationError
from schemas import WSMessage, VoteEvent, PollCreate, PollUpdateEvent

app = FastAPI()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# Dummy Auth-Check (In Produktion durch JWT-Validierung ersetzen)
async def verify_token(token: str = Header(...)):
    if token != "secret-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

@app.post("/polls")
async def create_poll(poll_data: PollCreate, db: AsyncSession = Depends(get_db)):
    # ... (rest of code)
    new_poll = Poll(title=poll_data.title)
    db.add(new_poll)
    await db.commit()
    await db.refresh(new_poll)
    for option in poll_data.options:
        db.add(Option(poll_id=new_poll.id, text=option.text))
    await db.commit()
    return {"id": new_poll.id}

@app.websocket("/ws/polls/{poll_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    poll_id: int, 
    token: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    # Authentifizierung
    if token != "secret-token":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(poll_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_json()
            try:
                # Validierung gegen Pydantic Schema
                message = WSMessage.model_validate(raw_data)
                
                if isinstance(message, VoteEvent):
                    new_vote = Vote(option_id=message.option_id)
                    db.add(new_vote)
                    await db.commit()
                    
                    # Broadcast update
                    await manager.broadcast(
                        poll_id,
                        PollUpdateEvent(message="New vote cast", total_votes=1),
                    )
            except ValidationError:
                await websocket.send_json({"error": "Invalid message format"})
    except WebSocketDisconnect:
        await manager.disconnect(poll_id, websocket)
