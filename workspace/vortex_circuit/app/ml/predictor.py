"""Statistischer Failure-Predictor und Service-Health-Score.

Berechnet Metriken zur Vorhersage von Service-Ausfällen und ermittelt
einen aggregierten Health-Score basierend auf Fehlerraten und Latenzen.
"""


class FailurePredictor:
    """Klasse zur Berechnung von Health-Scores und Ausfallwahrscheinlichkeiten."""
    
    def __init__(self) -> None:
        pass
        
    def calculate_health_score(
        self, 
        total_requests: int, 
        failed_requests: int, 
        recent_failures: int, 
        avg_latency_ms: float
    ) -> float:
        """
        Berechnet einen Health-Score von 0.0 (tot) bis 100.0 (perfekt).
        
        Args:
            total_requests: Gesamtzahl der Anfragen im Beobachtungszeitraum.
            failed_requests: Anzahl der fehlgeschlagenen Anfragen.
            recent_failures: Anzahl der Fehler in der jüngsten Vergangenheit (z.B. letzte Minute).
            avg_latency_ms: Durchschnittliche Latenz in Millisekunden.
            
        Returns:
            Ein Score zwischen 0.0 und 100.0.
        """
        if total_requests == 0:
            return 100.0
            
        failure_rate = failed_requests / total_requests
        
        # Basis-Score basierend auf der allgemeinen Fehlerrate
        score = 100.0 * (1.0 - failure_rate)
        
        # Abzug für kürzliche Fehler (höheres Gewicht, da sie auf ein akutes Problem hindeuten)
        penalty_recent = min(recent_failures * 5.0, 30.0)
        score -= penalty_recent
        
        # Abzug für hohe Latenz (ab 500ms beginnt die Degradation)
        if avg_latency_ms > 500.0:
            latency_penalty = min((avg_latency_ms - 500.0) / 100.0, 20.0)
            score -= latency_penalty
            
        return max(0.0, min(100.0, score))
        
    def predict_failure_probability(self, recent_failure_rate: float, trend: float) -> float:
        """
        Sagt die Wahrscheinlichkeit eines Ausfalls in naher Zukunft voraus.
        
        Args:
            recent_failure_rate: Die aktuelle Fehlerrate (0.0 bis 1.0).
            trend: Der Trend der Fehlerrate (-1.0 für stark sinkend, 1.0 für stark steigend).
            
        Returns:
            Wahrscheinlichkeit (0.0 bis 1.0).
        """
        # Einfaches statistisches Modell: Aktuelle Rate plus gewichteter Trend
        prob = recent_failure_rate + (trend * 0.5)
        return max(0.0, min(1.0, prob))

# Singleton-Instanz für die einfache Nutzung in der API
predictor = FailurePredictor()
