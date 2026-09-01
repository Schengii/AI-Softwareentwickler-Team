from fastapi import FastAPI, Request, HTTPException, status
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, requests: int, seconds: int):
        self.requests = requests
        self.seconds = seconds
        self.history = defaultdict(list)

    async def __call__(self, request: Request):
        client_ip = request.client.host
        now = time.time()
        
        # Filter old requests
        self.history[client_ip] = [t for t in self.history[client_ip] if now - t < self.seconds]
        
        if len(self.history[client_ip]) >= self.requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later."
            )
        
        self.history[client_ip].append(now)
