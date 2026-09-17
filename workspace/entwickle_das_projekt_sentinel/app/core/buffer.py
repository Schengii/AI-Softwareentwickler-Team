import collections

from app.core.config import get_settings

settings = get_settings()

class TelemetryBuffer:
    def __init__(self, maxlen: int = settings.BUFFER_MAX_SIZE):
        self.buffer = collections.deque(maxlen=maxlen)
        self.maxlen = maxlen

    def add(self, item: dict) -> bool:
        if len(self.buffer) >= self.maxlen:
            return False
        self.buffer.append(item)
        return True

    def pop_all(self) -> list:
        items = list(self.buffer)
        self.buffer.clear()
        return items

telemetry_buffer = TelemetryBuffer()
