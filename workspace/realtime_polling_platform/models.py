from pydantic import BaseModel, Field, validator
import html

class UserInput(BaseModel):
    # Beispiel für Input-Sanitization: Entfernung von HTML-Tags
    username: str = Field(..., min_length=3, max_length=50)
    comment: str = Field(..., max_length=500)

    @validator('comment')
    def sanitize_comment(cls, v):
        return html.escape(v)
