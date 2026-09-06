# 📌 event_relay – Projekt-Status & Checkpoint

- **Letzte Aktualisierung:** `2026-09-06 12:50:47 UTC`
- **Aktueller Status:** 🔴 Kritischer Befund ungelöst – NICHT einsatzbereit (Backlog-Ticket offen)
- **Zuletzt bearbeitete Aufgabe:** Dark-Mode Dashboard für Event-Relay implementiert

## 📁 Wichtige Projektkomponenten & Dateien
- `Dockerfile`
- `app/database.py`
- `app/kafka_client.py`
- `app/main.py`
- `app/models.py`
- `app/resilience.py`
- `app/schemas.py`
- `app/security.py`
- `app/worker.py`
- `design_status.json`
- `docker-compose.yml`
- `docs/adr/0001-kafka-statt-nats-f-r-event-broker.md`
- `pytest.ini`
- `requirements.txt`
- `setup_frontend.py`
- `tests/test_dashboard.py`
- `tests/test_main.py`
- `tests/test_resilience.py`

## 🧪 Verifikations- & Test-Status
- **Tests bestanden:** Ausstehend / Fehlgeschlagen ⚠️

## 🔴 Offener kritischer Befund (Backlog-Ticket)
- **Ticket:** `unresolved-governance-critical-event_relay` (Status: `blocked`, bisherige Wiederholungsversuche: 0)
- **Befund:**
  > 🔴 Kritische Probleme (müssen behoben werden)
1. **Import-Fehler & Zirkuläre Abhängigkeiten:** In `app/kafka_client.py` wird `from app.resilience import resilience` importiert, aber `resilience` ist keine globale Instanz in `app/resilience.py` (dort steht sogar `# Remove global instance`). Dies führt zu einem `ImportError`.
   * **Fix:** `app/main.py` sollte die `ResilienceManager`-Instanz injizier
- Dieses Projekt gilt trotz einer eventuell bestandenen Testsuite NICHT als einsatzbereit, solange dieses Ticket offen ist. `python main.py --work-backlog` greift es automatisch erneut auf (begrenzte Anzahl Versuche, siehe config.MAX_GOVERNANCE_TICKET_RETRIES).

## 🎯 Nächste empfohlene Schritte (Next Actions)
1. Offenen kritischen Befund aus Ticket `unresolved-governance-critical-event_relay` beheben (siehe oben).
2. Danach `/run-tests` bzw. einen neuen Lauf anstoßen, um das Ticket zu schließen.
