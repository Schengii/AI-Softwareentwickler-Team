# tests/test_evaluator.py
from app.services.evaluator import compute_percentage_bucket


def test_consistent_hashing_determinism():
    bucket1 = compute_percentage_bucket("flag_checkout", "usr_123")
    bucket2 = compute_percentage_bucket("flag_checkout", "usr_123")
    assert bucket1 == bucket2
    assert 0 <= bucket1 <= 99

def test_consistent_hashing_distribution_bounds():
    buckets = [compute_percentage_bucket("flag_v1", f"user_{i}") for i in range(1000)]
    assert min(buckets) >= 0 and max(buckets) < 100
