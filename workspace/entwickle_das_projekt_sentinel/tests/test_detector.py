from app.core.detector import ZScoreDetector


def test_detector_warmup():
    detector = ZScoreDetector(window_size=5, threshold=1.0)
    device_id = "test_device"
    metric = "temp"
    
    # Erstes Element (Warmup)
    is_anomaly, score = detector.process(device_id, metric, 10.0)
    assert is_anomaly is False
    assert score == 0.0
    
    # Zweites Element (Warmup abgeschlossen, aber stdev könnte noch 0 sein, wenn Werte gleich sind)
    is_anomaly, score = detector.process(device_id, metric, 10.0)
    assert is_anomaly is False
    assert score == 0.0


def test_detector_anomaly_detection():
    # Wir nutzen die echte Implementierung aus app.core.detector
    detector = ZScoreDetector(window_size=5, threshold=1.0)
    device_id = "test_device"
    metric = "temp"
    
    # Baseline aufbauen mit Variation, damit stdev > 0 ist
    values = [10.0, 11.0, 10.0, 12.0, 10.0]
    for v in values:
        detector.process(device_id, metric, v)
        
    # Deutliche Abweichung provozieren
    is_anomaly, score = detector.process(device_id, metric, 100.0)
    
    # Assertions
    assert is_anomaly is True
    assert score > 1.0
