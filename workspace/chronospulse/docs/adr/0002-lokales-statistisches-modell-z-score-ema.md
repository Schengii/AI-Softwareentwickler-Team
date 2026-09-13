# Lokales statistisches Modell (Z-Score & EMA) statt Deep Learning für Echtzeit-Anomalien

Status: Angenommen

## Kontext

Wir benötigen eine performante, echtzeitfähige Anomalieerkennung für den Ingestion-Stream. Optionen waren: 1) Deep Learning (Autoencoder, LSTM), 2) Isolation Forest, 3) Statistische Modelle (Z-Score, EMA).

## Entscheidung

Entscheidung für ein lokales statistisches Modell (Exponential Moving Average & Z-Score).

## Konsequenzen

Vorteile: O(1) Zeit- und Platzkomplexität pro Metrik, keine Trainingsphase nötig, extrem schnell. Nachteile: Erkennt keine komplexen saisonalen Muster, empfindlich gegenüber 'Vergiftung' durch langanhaltende Anomalien (daher wird das EMA-Update bei extremen Z-Scores ausgesetzt).
