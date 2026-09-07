# Locust & k6 für API-Durchsatz- und Frontend-Performance-Tests

Status: Angenommen

## Kontext

Die Webanwendung (Kanban- & Zeiterfassungs-Tool) muss unter einer Last von mindestens 50 gleichzeitigen Benutzern stabile Antwortzeiten (< 200ms p95) und hohen API-Durchsatz gewährleisten.

## Entscheidung

Einsatz von Locust (Python-basiert) als primäres Load-Testing-Tool in 'tests/load/locustfile.py' mit HttpUser und dynamic Host Injection, ergänzt durch ein k6-Skript ('tests/load/k6_scenario.js') für High-Throughput-Benchmarking.

## Konsequenzen

Genaue Messbarkeit von 50+ concurrent Users. Verwendungsfähigkeit für CI/CD Smoke-Tests und erweiterte Stress-Tests. Relative Endpunkt-Pfade erlauben flexible Ausführung gegen Dev, Staging und Prod.
