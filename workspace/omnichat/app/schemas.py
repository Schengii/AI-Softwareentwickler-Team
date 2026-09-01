from typing import Literal, Union
from uuid import UUID

from pydantic import BaseModel, RootModel


class MessageEvent(BaseModel):
    type: Literal["message"] = "message"
    content: str
    channel_id: UUID

class TypingEvent(BaseModel):
    type: Literal["typing"] = "typing"
    user_id: str

ChatEvent = RootModel[Union[MessageEvent, TypingEvent]]
