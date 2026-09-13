# Auszug aus app/utils/resilience.py
# - CircuitBreaker: Statusverwaltung (CLOSED, OPEN, HALF_OPEN), Failure Thresholds, Cooldown
# - ExponentialBackoff: Full-Jitter mit secrets.SystemRandom() gegen Thundering Herd
# - AdaptiveBackpressure: Concurrency-Limiting, Load Shedding & Queue Capacity Control
