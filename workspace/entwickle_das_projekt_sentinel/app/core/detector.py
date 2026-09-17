import collections
import statistics

from app.core.config import get_settings

settings = get_settings()

class ZScoreDetector:
    def __init__(self, window_size: int = settings.WINDOW_SIZE, threshold: float = settings.Z_SCORE_THRESHOLD):
        self.window_size = window_size
        self.threshold = threshold
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=window_size))

    def process(self, device_id: str, metric: str, value: float) -> tuple[bool, float]:
        key = f"{device_id}:{metric}"
        history = self.history[key]
        
        if len(history) < 2:
            history.append(value)
            return False, 0.0
            
        mean = statistics.mean(history)
        stdev = statistics.stdev(history)
        
        if stdev == 0:
            z_score = 0.0
        else:
            z_score = (value - mean) / stdev
            
        is_anomaly = abs(z_score) > self.threshold
        history.append(value)
        
        return is_anomaly, z_score

detector = ZScoreDetector()
