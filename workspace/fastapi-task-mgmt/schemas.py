from pydantic import BaseModel

class TaskBase(BaseModel):
    title: str
    status: str = "open"

class TaskCreate(TaskBase):
    pass

class Task(TaskBase):
    id: int
    user_id: int

    class Config:
        from_attributes = True

class UserCreate(BaseModel):
    username: str
    password: str
