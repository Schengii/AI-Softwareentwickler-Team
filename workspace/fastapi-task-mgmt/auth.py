import os
import warnings
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models

load_dotenv()

# Fällt bewusst NICHT hart (kein raise) auf einen fehlenden SECRET_KEY zurück - lokale
# Entwicklung/Tests sollen ohne .env-Setup lauffähig bleiben (siehe tests/test_api.py, das
# main.py/auth.py ohne eigene Umgebungsvariablen importiert). Der Fallback ist bewusst
# unverkennbar unsicher benannt und meldet sich zusätzlich per Warnung, statt eine
# Produktionsinstanz still mit einem öffentlich im Quellcode stehenden Schlüssel laufen zu
# lassen (siehe .env.example für die erwartete lokale Einrichtung).
_INSECURE_DEV_FALLBACK_SECRET_KEY = "SUPER_SECRET_KEY_CHANGE_ME_IN_PROD"
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    warnings.warn(
        "SECRET_KEY ist nicht gesetzt (Umgebungsvariable oder .env, siehe .env.example) - "
        "verwende einen unsicheren Entwicklungs-Platzhalter. NIEMALS so in Produktion "
        "einsetzen, jeder mit Zugriff auf den Quellcode könnte sonst gültige Tokens fälschen.",
        stacklevel=2,
    )
    SECRET_KEY = _INSECURE_DEV_FALLBACK_SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(models.get_db),
) -> models.User:
    """Löst den per Bearer-Token authentifizierten Nutzer auf - Standard-FastAPI-Dependency
    für jeden geschützten Endpunkt (siehe main.py: create_task/read_tasks). Vorher gab es in
    main.py nur einen Stub gleichen Namens, der NIE als Dependency eingesetzt wurde und einen
    fest verdrahteten Nutzer zurückgab - keine echte Authentifizierung."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültige oder abgelaufene Anmeldedaten.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    result = await db.execute(select(models.User).where(models.User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user
