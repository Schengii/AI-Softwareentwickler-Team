# React SPA mit TypeScript, Vite & API-Fallback-Strategie für Observability-Dashboard

Status: Angenommen

## Kontext

Das Dashboard benötigt zuverlässigen Datenzugriff auf Echtzeit-Metriken, Anomalien, Traces und Copilot-Empfehlungen über REST-Endpunkte (/api/v1/*).

## Entscheidung

Implementierung eines typsicheren API-Clients mit Vite Proxy, Axios/Fetch-Wrapper und automatischem, leisem Fallback auf strukturierte Mock-Daten bei HTTP- oder Verbindungsfehlern.

## Konsequenzen

Das Frontend kann nahtlos mit einem echten Backend kommunizieren oder bei Netzwerkfehlern/Entwicklungsumgebung auf typisierte Fallback-Mocks zurückgreifen, ohne dass der UI-Render-Prozess fehlschlägt.
