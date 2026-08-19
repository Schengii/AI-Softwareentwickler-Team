# app/core/config.py
from pydantic import BaseSettings, EmailStr

class Settings(BaseSettings):
    # JWT
    secret_key: str = "super-secret-key-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # E‑Mail (Dummy‑SMTP für Demo)
    smtp_host: str = "localhost"
    smtp_port: int = 1025   # `python -m smtpd -c DebuggingServer -n localhost:1025`
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: EmailStr = "no-reply@jobsuche.de"

    # Uploads
    upload_dir: str = "uploads"

    class Config:
        env_file = ".env"

settings = Settings()
