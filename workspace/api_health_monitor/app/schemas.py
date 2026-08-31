from pydantic import BaseModel, Field
from typing import Annotated, Union, List, Optional

class CheckCreate(BaseModel):
    url: str
    interval: int = 60

from typing import Literal

class AlertEvent(BaseModel):
    type: Literal["alert"] = "alert"
    check_id: str
    message: str

class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    check_id: str
    status: str

class WSMessage(BaseModel):
    # Diskriminiertes Union-Modell für WebSocket-Nachrichten
    data: Annotated[Union[AlertEvent, StatusEvent], Field(discriminator='type')]
