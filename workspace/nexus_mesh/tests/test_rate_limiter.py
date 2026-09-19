import time


# Mock-Klasse für Token Bucket, um die Logik zu testen
class TokenBucket:
    def __init__(self, capacity, refill_rate):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
    
    def consume(self):
        if self.tokens > 0:
            self.tokens -= 1
            return True
        return False

def test_token_bucket_consumption():
    bucket = TokenBucket(capacity=2, refill_rate=1)
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False
