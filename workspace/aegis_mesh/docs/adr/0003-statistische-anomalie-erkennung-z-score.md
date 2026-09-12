# Statistische Anomalie-Erkennung (Z-Score) statt komplexer ML-Modelle

Status: Angenommen

## Kontext

Für die ML-gestützte Anomalie-Erkennung zur Berechnung des Abuse-Scores musste entschieden werden, ob ein komplexes Machine-Learning-Modell (z.B. Isolation Forest, Autoencoder) oder eine leichtgewichtige statistische Methode verwendet wird.

## Entscheidung

Wir verwenden eine statistische Anomalie-Erkennung basierend auf Z-Score und Moving Average. Der Abuse-Score (0.0 - 1.0) wird aus der Abweichung der aktuellen Request-Rate vom historischen Mittelwert (in Standardabweichungen) berechnet.

## Konsequenzen

Vorteile: Sehr schnell, geringer Speicherbedarf (In-Memory Deque), keine externen Abhängigkeiten (wie PyTorch/TensorFlow), leicht nachvollziehbar. Nachteile: Erkennt keine komplexen, nicht-linearen Muster (z.B. langsame, schleichende Bot-Angriffe über Tage hinweg). Für den aktuellen Scope eines API-Gateways ist dies jedoch der optimale Trade-off.
