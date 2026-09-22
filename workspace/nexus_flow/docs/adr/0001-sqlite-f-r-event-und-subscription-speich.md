# SQLite für Event- und Subscription-Speicherung

Status: Angenommen

## Kontext

Das System benötigt eine persistente Speicherung für Events und Webhook-Subscriptions. Die Anforderungen verlangen explizit SQLite.

## Entscheidung

Wir nutzen SQLite mit SQLAlchemy (asyncio) als ORM und aktivieren den WAL-Modus für bessere Performance bei gleichzeitigen Lese-/Schreibzugriffen.

## Konsequenzen

Einfaches Setup ohne externe Abhängigkeiten. SQLite unterstützt im WAL-Modus (Write-Ahead Logging) ausreichend Nebenläufigkeit für mittlere Lasten. Bei extrem hohem Schreibdurchsatz könnte es zu Lock-Contention kommen.
