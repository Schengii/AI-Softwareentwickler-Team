import { useCallback, useEffect, useState } from "react";

import IncidentTable, { type Incident } from "./components/IncidentTable";
import WebhookSimulator from "./components/WebhookSimulator";

const API_BASE_URL = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * Fallback-Daten für die lokale Entwicklung/Demo, falls das Backend (noch) keine
 * Incidents liefert oder der API-Aufruf fehlschlägt – die Ansicht bleibt dadurch
 * immer benutzbar, statt eine leere Seite oder einen Absturz zu zeigen.
 */
const FALLBACK_INCIDENTS: Incident[] = [
  {
    id: 1,
    title: "API-Latenz überschreitet SLO (p95 > 800ms)",
    status: "open",
    created_at: new Date().toISOString(),
  },
  {
    id: 2,
    title: "Fehlgeschlagene Zahlungswebhooks (Stripe)",
    status: "acknowledged",
    created_at: new Date().toISOString(),
  },
];

function App() {
  const [incidents, setIncidents] = useState<Incident[]>(FALLBACK_INCIDENTS);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadIncidents = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/incidents`);
      if (!response.ok) {
        throw new Error(`Backend antwortete mit Status ${response.status}`);
      }
      const data: Incident[] = await response.json();
      setIncidents(data);
    } catch (error) {
      // Bewusst kein harter Fehlerzustand: die Demo-Daten bleiben sichtbar,
      // der Nutzer wird nur informativ auf den fehlgeschlagenen Live-Abruf hingewiesen.
      setLoadError(
        error instanceof Error ? error.message : "Unbekannter Fehler beim Laden der Incidents.",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadIncidents();
  }, [loadIncidents]);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 960, margin: "0 auto", padding: "2rem 1rem" }}>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ marginBottom: "0.25rem" }}>OpsPilot – Incident Dashboard</h1>
        <p style={{ color: "#555" }}>
          Übersicht aktueller Incidents und Werkzeug zum Simulieren eingehender Webhooks.
        </p>
      </header>

      <section style={{ marginBottom: "2.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
          <h2 style={{ margin: 0 }}>Incidents</h2>
          <button type="button" onClick={() => void loadIncidents()} disabled={isLoading}>
            {isLoading ? "Lädt…" : "Aktualisieren"}
          </button>
        </div>
        {loadError && (
          <p role="alert" style={{ color: "#b91c1c" }}>
            Live-Daten konnten nicht geladen werden ({loadError}) – zeige zuletzt bekannten Stand.
          </p>
        )}
        <IncidentTable incidents={incidents} />
      </section>

      <section>
        <h2>Webhook-Simulator</h2>
        <WebhookSimulator apiBaseUrl={API_BASE_URL} onIngested={() => void loadIncidents()} />
      </section>
    </main>
  );
}

export default App;
