# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-20
### Added
- Initial release of SynapseGate.
- Core Resilience: In-Memory Circuit Breaker with state management.
- Idempotency Engine: Prevents duplicate processing via `X-Idempotency-Key`.
- Asynchronous Event Bus with Dead-Letter-Queue (DLQ).
- Rate Limiting: Token-Bucket implementation.
- API Endpoints: `POST /api/v1/events`, `GET /api/v1/events/dlq`, `GET /health`.
- Testing: Unit tests and Locust load testing suite.
