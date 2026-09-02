# Containerized Deployment and CI/CD Pipeline

Status: Angenommen

## Kontext

Need for reproducible development, testing, and production deployment for IncidentPilot. Options: Manual setup vs. Docker Compose.

## Entscheidung

Docker Compose for orchestration, Multi-stage Dockerfile for security/size, GitHub Actions for CI.

## Konsequenzen

Multi-stage Docker builds reduce image size and attack surface. PostgreSQL in Compose ensures consistent dev environment. GitHub Actions automates testing against a real DB instance. Need to manage secrets via environment variables in production.
