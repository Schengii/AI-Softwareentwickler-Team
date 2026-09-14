import mmh3


def evaluate_percentage(user_id: str, flag_key: str, percentage: int) -> bool:
    """Murmur3-basiertes deterministisches Percentage-Rollout."""
    bucket_key = f"{flag_key}:{user_id}".encode()
    hash_val = abs(mmh3.hash(bucket_key)) % 100
    return hash_val < percentage

def test_hashing_determinism():
    """Stellt sicher, dass identische Inputs immer dieselbe Rollout-Entscheidung treffen."""
    flag = "new_checkout_flow"
    user_a = "user-uuid-1234"
    res1 = evaluate_percentage(user_a, flag, 20)
    res2 = evaluate_percentage(user_a, flag, 20)
    assert res1 == res2

def test_hashing_distribution():
    """Prüft Gleichverteilung bei 10.000 generierten User-IDs auf 20% Rollout (Toleranz: +-2.5%)."""
    flag = "canary_v2"
    total = 10_000
    percentage = 20
    hits = sum(1 for i in range(total) if evaluate_percentage(f"user-{i}", flag, percentage))
    actual_rate = (hits / total) * 100
    assert 17.5 <= actual_rate <= 22.5
