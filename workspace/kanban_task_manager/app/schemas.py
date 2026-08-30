from pydantic import BaseModel, Field

class TaskMovedPayload(BaseModel):
    type: str = Field(..., pattern="^task_moved$")
    taskId: int
    newStatus: str
