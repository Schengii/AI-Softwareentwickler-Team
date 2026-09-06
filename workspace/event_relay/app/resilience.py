import random
import time


class ResilienceManager:
    def __init__(self):
        self.retries = 3
        self.base_delay = 0.1

    def execute(self, func, *args, **kwargs):
        last_exception = None
        for attempt in range(self.retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                wait_time = self.base_delay * (2 ** attempt) + (random.uniform(0, 0.1))
                time.sleep(wait_time)
        raise last_exception

resilience = ResilienceManager()
