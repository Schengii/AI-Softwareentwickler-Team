# ADR-0003: Z-Score/EMA für Echtzeit-Anomalieerkennung statt komplexer ML-Modelle

Status: Angenommen

## Kontext

Für die Erkennung von Traffic-Spitzen (DDoS-Schutzheuristik) wird ein Anomalie-Scorer benötigt. Zur Auswahl standen:\n1. Komplexe ML-Modelle (Deep Learning, Isolation Forest)\n2. Einfache statistische Methoden (Z-Score mit Exponential Moving Average - EMA)\nDa das System im kritischen Pfad (Rate-Limiting) arbeitet, sind niedrige Latenz und geringer Speicherverbrauch essenziell.

## Entscheidung

Wir entscheiden uns für einen statistischen Z-Score/EMA Anomalie-Scorer. Der EMA passt sich dynamisch an veränderte Traffic-Muster an, während der Z-Score signifikante Abweichungen (Spitzen) erkennt. Dies ermöglicht eine Echtzeit-Auswertung ohne Performance-Einbußen.

## Konsequenzen

- **Vorteile:** Extrem geringe Latenz (O(1) Zeitkomplexität pro Request), minimaler Speicherverbrauch, keine Notwendigkeit für aufwendiges Modell-Training oder GPU-Ressourcen.\n- **Nachteile:** Erkennt nur lineare/statistische Abweichungen, keine komplexen Muster (z.B. langsame, schleichende DDoS-Angriffe).\n- **Zukünftige Einschränkungen:** Bei Bedarf an komplexerer Mustererkennung muss ein separates, asynchrones ML-Modell (z.B. Isolation Forest) hinzugefügt werden.
