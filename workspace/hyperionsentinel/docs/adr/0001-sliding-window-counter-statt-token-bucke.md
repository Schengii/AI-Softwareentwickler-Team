# Sliding-Window-Counter statt Token-Bucket für Rate-Limiting

Status: Angenommen

## Kontext

Für die Security- & Traffic-Shaping-Engine wird ein Rate-Limiting-Algorithmus benötigt. Zur Auswahl standen Token-Bucket (einfach, speichereffizient, erlaubt aber Bursts) und Sliding-Window-Counter/Log (präziser, glättet Traffic besser, verhindert plötzliche Lastspitzen).

## Entscheidung

Wir verwenden einen asynchronen Sliding-Window-Counter-Algorithmus. Er bietet die notwendige Präzision für geschäftskritische Security-Anwendungen und verhindert, dass Angreifer durch Ausnutzung von Burst-Fenstern das System überlasten.

## Konsequenzen

Höhere Genauigkeit bei der Traffic-Analyse und bessere Abwehr von DDoS-Spitzen. Erfordert jedoch etwas mehr Speicherplatz pro Client als Token-Bucket. Die Implementierung muss asynchron und performant erfolgen (z.B. via Redis Pipelining), um Latenzen gering zu halten.
