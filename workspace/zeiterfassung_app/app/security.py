# app/security.py
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plain password."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    return pwd_context.verify(plain, hashed)


class CurrentUser:
    def __init__(self, id: int = 1, username: str = "demo_user", email: str = "demo@example.com"):
        self.id = id
        self.username = username
        self.email = email


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    return CurrentUser()
