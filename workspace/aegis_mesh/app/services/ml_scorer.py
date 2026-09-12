"""
ML-gestützte Anomalie-Erkennung für AegisMesh.
Berechnet Abuse-Scores basierend auf statistischen Methoden (Z-Score und Moving Average).
"""

import math
import time
from collections import defaultdict, deque

from app.core.config import get_settings


class AnomalyScorer:
    """
    Berechnet einen Abuse-Score (0.0 bis 1.0) für Clients basierend auf
    ihrem Request-Verhalten im Vergleich zu ihrer eigenen Historie.
    """

    def __init__(self, window_size: int = 10, z_score_threshold: float = 3.0):
        self.window_size = window_size
        self.z_score_threshold = z_score_threshold
        
        # Speichert die Request-Timestamps pro Client (In-Memory Ringpuffer)
        self.client_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=1000))
        
        # Speichert die historischen Raten pro Fenster pro Client
        self.client_rates: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window_size))

    def record_request(self, client_id: str) -> None:
        """Registriert einen Request-Timestamp für den Client."""
        now = time.time()
        self.client_history[client_id].append(now)

    def calculate_current_rate(self, client_id: str, window_seconds: float = 60.0) -> float:
        """Berechnet die aktuelle Request-Rate (Requests pro window_seconds)."""
        now = time.time()
        history = self.client_history[client_id]
        
        # Entferne alte Einträge außerhalb des Fensters
        while history and history[0] < now - window_seconds:
            history.popleft()
            
        return float(len(history))

    def update_and_get_score(self, client_id: str) -> float:
        """
        Aktualisiert die Historie und berechnet den Abuse-Score (0.0 - 1.0)
        basierend auf der aktuellen Rate im Vergleich zur historischen Rate (Z-Score).
        """
        current_rate = self.calculate_current_rate(client_id)
        historical_rates = self.client_rates[client_id]

        # Wenn nicht genug Historie vorhanden ist, sammeln wir erst Daten
        if len(historical_rates) < 3:
            historical_rates.append(current_rate)
            return 0.0

        # Moving Average (Mean)
        mean = sum(historical_rates) / len(historical_rates)
        
        # Standardabweichung (Population Standard Deviation)
        variance = sum((x - mean) ** 2 for x in historical_rates) / len(historical_rates)
        std_dev = math.sqrt(variance)

        # Aktuelle Rate für den nächsten Zyklus speichern
        historical_rates.append(current_rate)

        # Edge-Case: Konstante Rate in der Vergangenheit
        if std_dev == 0:
            if current_rate > mean * 1.5:  # 50% plötzlicher Anstieg
                score = min((current_rate - mean) / (mean or 1), 1.0)
                return round(score, 4)
            return 0.0

        # Z-Score berechnen: Wie viele Standardabweichungen weicht die aktuelle Rate ab?
        z_score = (current_rate - mean) / std_dev

        # Negative Z-Scores (weniger Requests als üblich) sind keine Anomalie
        if z_score <= 0:
            return 0.0

        # Normalisiere Z-Score auf 0.0 - 1.0
        # Ein Z-Score >= z_score_threshold ergibt einen Score von 1.0 (maximaler Abuse)
        score = min(z_score / self.z_score_threshold, 1.0)
        
        return round(score, 4)


# Singleton Instanz für den globalen Zugriff im FastAPI Lifecycle
_scorer_instance = None

def get_anomaly_scorer() -> AnomalyScorer:
    """Liefert die Singleton-Instanz des AnomalyScorers."""
    global _scorer_instance
    if _scorer_instance is None:
        settings = get_settings()
        # Threshold könnte aus den Settings abgeleitet werden, hier statisch 3.0 für 99.7% Konfidenz
        _scorer_instance = AnomalyScorer(window_size=10, z_score_threshold=3.0)
    return _scorer_instance
