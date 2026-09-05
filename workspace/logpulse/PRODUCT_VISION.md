# Logpulse Produktvision & MVP-Definition

## 🎯 Produktvision & Zielgruppen-Definition
- **Vision Statement:** Logpulse ist der leichtgewichtige, zentrale Log-Aggregator, der Microservice-Teams durch sofortige Transparenz und schnelle Fehlerdiagnose befähigt.
- **Zielgruppe / Personas:** DevOps-Engineers, Backend-Entwickler, SREs.
- **Core Value Proposition:** Einfache, schnelle Log-Aggregation mit einer performanten REST-API und einem intuitiven Dark-Mode Dashboard zur Fehleranalyse.

## 📦 MVP-Scope & Feature-Priorisierung (MoSCoW)
### 🔴 Must-Have (MVP)
- **Log-Ingestion API:** REST-Endpunkt für JSON-Log-Daten.
- **Datenhaltung:** SQLite-Speicherung mit Indizes auf `timestamp` und `service_name`.
- **Dashboard:** Web-UI zur Anzeige der letzten 100 Logs.
- **Filterung:** Suche nach `service_name` und `log_level`.
- **Zeitraum:** Anzeige der Logs innerhalb eines wählbaren Zeitfensters.

### 🟡 Should-Have (v1.1)
- **Log-Levels:** Aggregierte Statistiken (Count pro Level).
- **Suche:** Volltextsuche in der Log-Message.

### 🟢 Could-Have (Backlog)
- **Alerting:** Webhooks bei `CRITICAL` Log-Einträgen.
- **Archivierung:** Automatisches Löschen von Logs älter als 30 Tage.

### ⚪ Won't-Have (Now)
- **Authentifizierung:** (Vorerst vertrauensbasiertes Netzwerk).
- **Syslog-Support:** (Fokus liegt auf JSON-REST).

## 📝 User Stories & Akzeptanzkriterien

### Story 1: Log-Ingestion
- **Als:** Microservice
- **Möchte ich:** Log-Daten via REST-API senden
- **Damit:** Diese zentral gespeichert und analysiert werden können
- **Akzeptanzkriterien:**
  - Given ein valider JSON-Log-Payload, When POST /api/logs, Then wird der Log mit Status 201 gespeichert.

### Story 2: Log-Abfrage
- **Als:** Entwickler
- **Möchte ich:** Logs nach Service und Level filtern
- **Damit:** Ich Fehler in einem spezifischen Dienst schneller finde
- **Akzeptanzkriterien:**
  - Given Logs existieren, When GET /api/logs?service=auth&level=ERROR, Then werden nur entsprechende Einträge zurückgegeben.

### Story 3: Dashboard-Ansicht
- **Als:** DevOps-Engineer
- **Möchte ich:** Ein Dark-Mode Dashboard sehen
- **Damit:** Ich den Systemzustand ohne Augenbelastung überwachen kann
- **Akzeptanzkriterien:**
  - Given das Dashboard ist geladen, When ich die Seite öffne, Then wird das UI im Dark-Mode gerendert.

## 🗺️ Release-Roadmap
- **Sprint / Phase 1 (MVP Launch):** API-Ingestion, SQLite-Backend, Basis-Dashboard (Tabellarische Ansicht).
- **Sprint / Phase 2 (Wachstum & Skalierung):** Volltextsuche, Log-Statistiken, Performance-Optimierung.
