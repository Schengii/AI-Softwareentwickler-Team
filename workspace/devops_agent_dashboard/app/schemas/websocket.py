from typing import Literal

from pydantic import BaseModel, Field


class AgentStatusMessage(BaseModel):
    type: Literal["agent_status"] = "agent_status"
    agent_id: str
    status: str
    current_task: str | None = None
    success_rate: float

class SystemEventMessage(BaseModel):
    type: Literal["system_event"] = "system_event"
    event_id: str
    level: str
    message: str
    source: str

class WSMessageWrapper(BaseModel):
    """
    Echtes Pydantic-Wrapper-Modell für WebSocket-Nachrichten mit Diskriminator.
    Garantiert lauffähige `.model_validate()`-API.
    """
    payload: AgentStatusMessage | SystemEventMessage = Field(..., discriminator="type")
