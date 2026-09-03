# IncidentPilot Frontend

React SPA (Vite + TypeScript), siehe `docs/adr/0001-react-spa-mit-vite-und-resilienter-api-c.md`.

## Struktur
- `src/api/`: API-Client (Axios mit Auth-/Fehler-Interceptoren, `client.ts`) und die einzelnen
  Endpunkt-Funktionen (`checks.ts`)
- `src/hooks/`: Custom Hooks für Datenabfrage (`useChecks`)
- `src/pages/`: Seiten (aktuell: `Dashboard` - listet Uptime-Checks und legt neue an)
- `src/types.ts`: Typen, die die Backend-Schemas (`app/models.py`, `architecture/openapi.yaml`)
  widerspiegeln

## Setup

```bash
npm install
npm run dev      # Dev-Server auf http://localhost:5173, proxyt /api -> http://localhost:8000
npm run build    # tsc + Produktions-Build nach dist/
npm test         # vitest
```

`VITE_API_BASE_URL` (optional, `.env`) überschreibt die in `src/api/client.ts` konfigurierte
Basis-URL für lokale Entwicklung gegen ein laufendes Backend.

## Bekannter Stand

Aktuell nur an die bereits implementierten Backend-Endpunkte (`GET/POST /checks`,
`GET /checks/{id}/status`) angebunden. `architecture/openapi.yaml` definiert zusätzlich
`/alerts/configs`, `/alerts/test` und `/metrics` - diese existieren weder im Backend
(`app/main.py`) noch im Frontend und sind bewusst nicht als Stub-Seiten vorgetäuscht.
