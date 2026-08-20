'''FastAPI Anwendung mit einem einfachen Health‑Check Endpoint.

GET /health  →  {"status": "ok"}

Dieses Modul kann direkt mit ``uvicorn main:app`` gestartet werden.
'''

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/health", response_model=dict, summary="Health‑Check", tags=["monitoring"])
def health_check() -> JSONResponse:
    """Gibt den Status der Anwendung zurück.

    Returns
    -------
    JSONResponse
        JSON mit dem Schlüssel ``status`` und dem Wert ``ok``.
    """
    return JSONResponse(content={"status": "ok"})

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
