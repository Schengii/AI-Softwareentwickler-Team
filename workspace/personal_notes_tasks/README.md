# API Test-Dokumentation

Dieses Projekt enthält eine FastAPI-Anwendung mit CRUD-Endpunkten für Notizen und Aufgaben.

## Test-Suite
Die Tests befinden sich in `test_main.py` und nutzen `pytest` sowie `TestClient`.

### Ausführung
1. Abhängigkeiten installieren:
   ```bash
   pip install pytest httpx
   ```
2. Tests ausführen:
   ```bash
   pytest test_main.py
   ```

### Abgedeckte Szenarien
- **Notizen:** Erstellen, Auflisten, Löschen.
- **Aufgaben:** Erstellen, Auflisten, Status-Update (erledigt).
- **Fehlerbehandlung:** 404-Fehler bei nicht existierenden Aufgaben.
- **Isolation:** `pytest.fixture` stellt sicher, dass der In-Memory-Speicher vor jedem Test geleert wird.
