# app/core/email.py
import aiosmtplib
from email.message import EmailMessage
from fastapi import BackgroundTasks

from app.core.config import settings

async def send_email(to: str, subject: str, body: str):
    """Versendet eine E‑Mail über SMTP (asynchron)."""
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=False,
    )

def schedule_email(background: BackgroundTasks, to: str, subject: str, body: str):
    """Wrapper für FastAPI‑BackgroundTasks."""
    background.add_task(send_email, to, subject, body)
