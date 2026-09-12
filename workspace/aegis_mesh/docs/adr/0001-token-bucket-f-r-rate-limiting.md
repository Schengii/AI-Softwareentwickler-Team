# Token-Bucket für Rate-Limiting

Status: Angenommen

## Kontext

Wir benötigen einen performanten, speichereffizienten Algorithmus für das Rate-Limiting, der Bursts erlaubt, aber eine konstante Refill-Rate garantiert. Optionen waren Token-Bucket, Sliding-Window Log und Sliding-Window Counter.

## Entscheidung

Wir entscheiden uns für den Token-Bucket-Algorithmus. Er ist speichereffizient (benötigt nur die aktuelle Token-Anzahl und den letzten Refill-Timestamp pro Key) und lässt sich atomar in Redis oder In-Memory implementieren.

## Konsequenzen

Einfache, speichereffiziente Implementierung. Erlaubt Bursts, was für APIs oft gewünscht ist. Keine exakte Historie der Requests innerhalb eines Fensters. Bursts können zu kurzzeitigen Lastspitzen am Backend führen, was durch ML-Scoring mitigiert werden muss.
