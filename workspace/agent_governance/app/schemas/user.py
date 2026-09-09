from pydantic import BaseModel


class UserCreate(BaseModel):
    """Schema für die Benutzerregistrierung."""
    username: str  # Eindeutiger Benutzername
    password: str  # Passwort im Klartext (wird im Service gehasht)

class Token(BaseModel):
    """Authentifizierungs-Token-Schema."""
    access_token: str  # JWT Token
    token_type: str    # Typ des Tokens (üblicherweise 'bearer')
