"""AetherMesh Engine - Realtime Streaming API Router.

Stellt SSE- (Server-Sent Events) und WebSocket-Endpunkte für
Live-Metriken, Job-Events und Backpressure-Status bereit.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/v1/stream", tags=["Streaming"])


@router.get("/events")
async def stream_events_sse() -> StreamingResponse:
    """Server-Sent Events (SSE) Stream für kontinuierliche Engine- & Job-Updates."""
    from app.main import metrics_aggregator, backpressure_controller

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                metrics = await metrics_aggregator.get_current_metrics()
                payload = {
                    "metrics": metrics,
                    "backpressure": {
                        "is_throttled": backpressure_controller.is_throttled,
                        "current_depth": backpressure_controller.current_depth,
                    },
                }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws")
async def stream_websocket(websocket: WebSocket) -> None:
    """WebSocket-Verbindung für bidirektionale Metrik- und Job-Status-Übertragung."""
    await websocket.accept()
    from app.main import metrics_aggregator, backpressure_controller

    try:
        while True:
            metrics = await metrics_aggregator.get_current_metrics()
            await websocket.send_json({
                "type": "metrics_update",
                "data": metrics,
                "throttled": backpressure_controller.is_throttled,
            })
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
