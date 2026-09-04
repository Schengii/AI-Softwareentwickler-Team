import re

from starlette.types import ASGIApp, Receive, Scope, Send


class PIIFilterMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app
        # Einfaches Regex für E-Mails als Beispiel für PII-Maskierung
        self.email_pattern = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        async def wrapped_send(message: dict):
            if message.get("type") == "http.response.body":
                body = message.get("body", b"").decode("utf-8", errors="ignore")
                masked_body = self.email_pattern.sub("[MASKED_PII]", body)
                message["body"] = masked_body.encode("utf-8")
            await send(message)

        await self.app(scope, receive, wrapped_send)
