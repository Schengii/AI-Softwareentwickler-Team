import math
import time

from pydantic import BaseModel, Field


class AnomalyScore(BaseModel):
    """Pydantic Modell für das Ergebnis der Anomalie-Prüfung."""
    is_anomaly: bool = Field(..., description="Gibt an, ob der aktuelle Traffic als Anomalie eingestuft wird")
    z_score: float = Field(..., description="Berechneter Z-Score des aktuellen Traffics")
    current_rate: float = Field(..., description="Aktuelle Request-Rate im Zeitfenster")
    mean_rate: float = Field(..., description="Erwartete Request-Rate (EMA)")

class TrafficAnomalyDetector:
    """
    Statistischer Z-Score/EMA Anomalie-Scorer zur Erkennung von Traffic-Spitzen.
    Verwendet Exponential Moving Average (EMA), um sich an verändernde Traffic-Muster anzupassen.
    """
    def __init__(self, alpha: float = 0.1, threshold: float = 3.0, min_samples: int = 10, window_size: float = 1.0):
        """
        Initialisiert den Anomalie-Detektor.
        
        :param alpha: Glättungsfaktor für den EMA (0 < alpha < 1). Höher = reagiert schneller auf Änderungen.
        :param threshold: Z-Score Schwellenwert für Anomalien (z.B. 3.0 für 99.7% Konfidenz).
        :param min_samples: Mindestanzahl an Samples, bevor eine Anomalie gemeldet wird.
        :param window_size: Größe des Zeitfensters in Sekunden zur Aggregation von Requests.
        """
        self.alpha = alpha
        self.threshold = threshold
        self.min_samples = min_samples
        self.window_size = window_size
        
        # State pro Key (z.B. IP-Adresse oder API-Key)
        # Struktur: key -> {"mean": float, "var": float, "count": int, "last_time": float, "current_window_count": int}
        self.state: dict[str, dict] = {}
        
    def record_request(self, key: str, current_time: float | None = None) -> None:
        """
        Registriert einen Request für einen bestimmten Key und aktualisiert die Statistiken,
        wenn das Zeitfenster abgelaufen ist.
        """
        if current_time is None:
            # time.monotonic() ist sicher für Zeitmessungen (kein Problem mit Systemzeit-Änderungen)
            current_time = time.monotonic()
            
        if key not in self.state:
            self.state[key] = {
                "mean": 0.0,
                "var": 0.0,
                "count": 0,
                "last_time": current_time,
                "current_window_count": 0
            }
            
        state = self.state[key]
        
        # Prüfe, ob das aktuelle Zeitfenster abgelaufen ist
        if current_time - state["last_time"] >= self.window_size:
            # Window ist abgelaufen, aktualisiere EMA und Varianz
            self._update_stats(key, float(state["current_window_count"]))
            
            # Starte neues Fenster
            state["current_window_count"] = 1
            state["last_time"] = current_time
        else:
            # Zähle Request im aktuellen Fenster
            state["current_window_count"] += 1

    def _update_stats(self, key: str, value: float) -> None:
        """Aktualisiert den Exponential Moving Average (EMA) und die Varianz."""
        state = self.state[key]
        
        if state["count"] == 0:
            state["mean"] = value
            state["var"] = 0.0
        else:
            diff = value - state["mean"]
            # Update Mean (EMA)
            state["mean"] = state["mean"] + self.alpha * diff
            # Update Variance (EMA der quadrierten Abweichungen)
            state["var"] = (1 - self.alpha) * (state["var"] + self.alpha * (diff ** 2))
            
        state["count"] += 1

    def check_anomaly(self, key: str) -> AnomalyScore:
        """
        Prüft, ob der aktuelle Traffic für den Key eine Anomalie (Traffic-Spitze) darstellt.

class AnomalyScorer:
    def __init__(self):
        self.detector = TrafficAnomalyDetector()
        
    def score_request(self, ip_address: str, count: int) -> dict:
        for _ in range(count):
            self.detector.record_request(key=ip_address)
        res = self.detector.check_anomaly(key=ip_address)
        return {"is_anomalous": res.is_anomaly, "score": res.z_score}
        """
        if key not in self.state:
            return AnomalyScore(is_anomaly=False, z_score=0.0, current_rate=0.0, mean_rate=0.0)
            
        state = self.state[key]
        current_rate = float(state["current_window_count"])
        
        # Nicht genug Datenpunkte für eine statistisch signifikante Aussage
        if state["count"] < self.min_samples:
            return AnomalyScore(is_anomaly=False, z_score=0.0, current_rate=current_rate, mean_rate=state["mean"])
            
        std_dev = math.sqrt(state["var"])
        
        # Z-Score Berechnung (Vermeidung von Division durch Null)
        if std_dev == 0:
            z_score = 0.0 if current_rate <= state["mean"] else float('inf')
        else:
            z_score = (current_rate - state["mean"]) / std_dev
            
        # Eine Anomalie liegt vor, wenn der Z-Score den Schwellenwert überschreitet
        # Wir interessieren uns nur für Traffic-Spitzen (z_score > threshold), nicht für Einbrüche
        is_anomaly = z_score > self.threshold
        
        return AnomalyScore(
            is_anomaly=is_anomaly,
            z_score=z_score,
            current_rate=current_rate,
            mean_rate=state["mean"]
        )
