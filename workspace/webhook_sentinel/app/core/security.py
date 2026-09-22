from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def setup_cors(app: FastAPI) -> None:
    """
    Configures CORS for the FastAPI application.
    Strictly avoids allow_origins=["*"] with allow_credentials=True.
    """
    app.add_middleware(
        CORSMiddleware,
        # Explicit whitelist of allowed origins. In production, this should be loaded from settings.
        allow_origins=[
            "https://trusted-frontend.example.com",
            "https://dashboard.example.com"
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Webhook-Signature", "X-Event-ID"],
    )
