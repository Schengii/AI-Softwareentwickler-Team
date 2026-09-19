from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "gateway_requests_total",
    "Total number of requests forwarded",
    ["service", "method", "status"]
)

REQUEST_LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Latency of forwarded requests",
    ["service"]
)

def get_metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
