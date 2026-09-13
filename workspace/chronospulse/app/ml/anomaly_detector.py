"""
ChronosPulse - Statistische ML-Anomalieerkennung
Implementiert Exponential Moving Average (EMA) und Z-Score.
"""

import math
from typing import Dict, Tuple

class AnomalyDetector:
    """
    Lokales statistisches ML-Modell zur Anomalieerkennung mittels
    Exponential Moving Average (EMA) und Z-Score.
    """
    def __init__(self, alpha: float = 0.1, threshold_z: float = 3.0):
        self.alpha = alpha
        self.threshold_z = threshold_z
        # State: (ema_mean, ema_variance) per metric_key
        self.state: Dict[str, Tuple[float, float]] = {}

    def _get_key(self, service: str, metric_name: str) -> str:
        return f"{service}::{metric_name}"

    def update_and_detect(self, service: str, metric_name: str, value: float) -> Tuple[bool, float, float]:
        """
        Aktualisiert die Statistiken und prüft auf Anomalien.
        Gibt (is_anomaly, z_score, expected_value) zurück.
        """
        key = self._get_key(service, metric_name)
        
        if key not in self.state:
            # Initialisierung mit Startwert
            self.state[key] = (value, 0.0)
            return False, 0.0, value
            
        ema_mean, ema_var = self.state[key]
        
        # Z-Score berechnen
        std_dev = math.sqrt(ema_var) if ema_var > 0 else 1.0
        z_score = (value - ema_mean) / std_dev if std_dev > 0 else 0.0
        
        is_anomaly = abs(z_score) > self.threshold_z
        
        # Update EMA (nur wenn keine extreme Anomalie, um das Modell nicht zu vergiften)
        if abs(z_score) < self.threshold_z * 2:
            diff = value - ema_mean
            new_mean = ema_mean + self.alpha * diff
            new_var = (1 - self.alpha) * (ema_var + self.alpha * diff**2)
            self.state[key] = (new_mean, new_var)
            
        return is_anomaly, z_score, ema_mean

# Singleton für die Anwendung
anomaly_detector = AnomalyDetector()
