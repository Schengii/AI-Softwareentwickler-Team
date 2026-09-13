"""
Asynchroner Workload-Analyzer für Durchsatzmetriken und Latenz-Drift.
"""

import time
from collections import deque
from typing import Dict, Any

class WorkloadAnalyzer:
    """
    Analysiert Durchsatz und Latenz-Drift von Jobs in Echtzeit.
    Nutzt ein Sliding-Window für aktuelle Metriken und eine Warmup-Phase
    zur Bestimmung einer Baseline.
    """

    def __init__(self, warmup_period_sec: float = 10.0, window_size: int = 1000):
        """
        Initialisiert den Analyzer.
        
        Args:
            warmup_period_sec: Dauer der Warmup-Phase in Sekunden.
            window_size: Maximale Anzahl an Jobs im Sliding-Window.
        """
        self.warmup_period_sec = warmup_period_sec
        self.window_size = window_size
        self.start_time = time.monotonic()
        
        self.latencies: deque[float] = deque(maxlen=window_size)
        self.completion_times: deque[float] = deque(maxlen=window_size)
        
        self.baseline_latency: float = 0.0
        self.is_warmed_up: bool = False

    def record_job(self, latency_sec: float) -> None:
        """
        Erfasst einen abgeschlossenen Job.
        
        Args:
            latency_sec: Die Verarbeitungsdauer des Jobs in Sekunden.
        """
        current_time = time.monotonic()
        self.latencies.append(latency_sec)
        self.completion_times.append(current_time)
        
        # Warmup-Phase abschließen und Baseline setzen
        if not self.is_warmed_up and (current_time - self.start_time) >= self.warmup_period_sec:
            self.is_warmed_up = True
            if self.latencies:
                self.baseline_latency = sum(self.latencies) / len(self.latencies)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Berechnet die aktuellen Metriken (Durchsatz, Latenz, Drift).
        
        Returns:
            Dict mit den berechneten Metriken.
        """
        current_time = time.monotonic()
        
        # Durchsatz (Jobs pro Sekunde) im aktuellen Fenster berechnen
        throughput = 0.0
        if len(self.completion_times) > 1:
            # Nur Events der letzten 60 Sekunden berücksichtigen für akkuraten Durchsatz
            recent_times = [t for t in self.completion_times if current_time - t <= 60.0]
            if len(recent_times) > 1:
                time_span = recent_times[-1] - recent_times[0]
                if time_span > 0:
                    throughput = len(recent_times) / time_span

        # Latenz und Drift berechnen
        current_avg_latency = 0.0
        drift = 0.0
        if self.latencies:
            current_avg_latency = sum(self.latencies) / len(self.latencies)
            if self.is_warmed_up and self.baseline_latency > 0:
                drift = (current_avg_latency - self.baseline_latency) / self.baseline_latency

        return {
            "is_warmed_up": self.is_warmed_up,
            "throughput_jps": round(throughput, 2),
            "current_avg_latency_sec": round(current_avg_latency, 4),
            "baseline_latency_sec": round(self.baseline_latency, 4),
            "latency_drift_pct": round(drift * 100, 2),
            "window_samples": len(self.latencies),
            "uptime_sec": round(current_time - self.start_time, 2)
        }


# Re-Export / Alias für PerformanceAnalyzer
PerformanceAnalyzer = WorkloadAnalyzer

