# ML-Modell-Integration und Persistenz in Telemetrie-Pipeline

Status: Angenommen

## Kontext

Der ML-Service war bisher ein Stub ohne echte Modell-Logik oder Persistenz. Es bestand die Anforderung, das Modell und die Datenbank-Anbindung zu implementieren.

## Entscheidung

Implementierung eines `joblib`-basierten Modell-Loaders mit Fallback-Heuristik und Integration der SQLAlchemy-Session zur Speicherung der Vorhersage-Ergebnisse.

## Konsequenzen

Das Modell wird nun dynamisch geladen. Falls kein Modell existiert, fällt das System auf eine Heuristik zurück, was die Robustheit erhöht. Die Vorhersagen werden nun in der Datenbank persistiert, was für Audit-Trails und zukünftiges Retraining notwendig ist.
