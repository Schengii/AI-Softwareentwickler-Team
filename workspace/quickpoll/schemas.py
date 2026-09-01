from pydantic import BaseModel
from typing import List, Union, Literal

class OptionCreate(BaseModel):
    text: str

class PollCreate(BaseModel):
    title: str
    options: List[OptionCreate]

class VoteCreate(BaseModel):
    option_id: int

# WebSocket Event Models
class VoteEvent(BaseModel):
    type: Literal["vote"] = "vote"
    option_id: int

class PollUpdateEvent(BaseModel):
    type: Literal["poll_update"] = "poll_update"
    message: str
    total_votes: int

WSMessage = Union[VoteEvent, PollUpdateEvent]
