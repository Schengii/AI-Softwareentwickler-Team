# app/security.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

import bcrypt

# Dedizierter ThreadPool für CPU-bound Krypto-Operationen
_executor = ThreadPoolExecutor(max_workers=4)

async def hash_password_async(password: str) -> str:
    """Hasht ein Passwort asynchron, ohne den Event-Loop zu blockieren."""
    def _hash():
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _hash)

async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Verifiziert ein Passwort asynchron, ohne den Event-Loop zu blockieren."""
    def _verify():
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _verify)
