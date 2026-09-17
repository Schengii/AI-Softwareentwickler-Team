# In-Memory Deque für Sliding-Window-Aggregation

Status: Angenommen

## Kontext

Sliding-Window-Aggregation erfordert das effiziente Hinzufügen von Metrik-Datenpunkten und das Entfernen abgelaufener Datenpunkte anhand eines Zeitstempels.

## Entscheidung

Verwendung von collections.deque mit zeitbasierter Bereinigung (sliding time window) pro Metrik/Tag-Kombination im Arbeitsspeicher.

## Konsequenzen

Geringe Latenz und einfacher Aufbau im Python-Speicher. Speicherverbrauch wächst linear mit der Anzahl der Events im Fenster; muss durch Time-to-Live (TTL) und Begrenzung pro Metrik bereinigt werden.
