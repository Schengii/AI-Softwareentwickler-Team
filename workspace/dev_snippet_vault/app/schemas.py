
import bleach
from pydantic import BaseModel, ConfigDict, Field, field_validator


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return bleach.clean(value, tags=[], attributes={}, strip=True)

class SnippetBase(BaseModel):
    title: str = Field(..., min_length=1, description="Darf nicht leer sein")
    code: str = Field(..., min_length=1)
    language: str = Field(..., min_length=1)
    description: str | None = None
    tags: str | None = None
    is_favorite: bool | None = False

    @field_validator('title', 'description', 'tags', mode='before')
    @classmethod
    def sanitize_fields(cls, v):
        return sanitize_text(v)

class SnippetCreate(SnippetBase):
    pass

class SnippetUpdate(BaseModel):
    title: str | None = Field(None, min_length=1)
    code: str | None = Field(None, min_length=1)
    language: str | None = Field(None, min_length=1)
    description: str | None = None
    tags: str | None = None
    is_favorite: bool | None = None

    @field_validator('title', 'description', 'tags', mode='before')
    @classmethod
    def sanitize_fields(cls, v):
        return sanitize_text(v)

class SnippetOut(SnippetBase):
    id: int
    
    model_config = ConfigDict(from_attributes=True)
