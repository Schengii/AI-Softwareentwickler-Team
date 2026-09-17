# Z-Score für Anomalie-Erkennung

Status: Angenommen

## Kontext

Es wird eine automatische Anomalie-Erkennung für die Telemetriedaten gefordert.

## Entscheidung

Verwendung des Z-Score-Verfahrens zur Anomalie-Erkennung. Ein Z-Score > 3 oder < -3 wird als Anomalie (Incident) gewertet.

## Konsequenzen

Einfach zu implementieren und performant. Setzt eine Normalverteilung der Daten voraus. Benötigt einen gleitenden Durchschnitt und eine Standardabweichung (z.B. über ein Zeitfenster oder die letzten N Werte pro Metrik).
