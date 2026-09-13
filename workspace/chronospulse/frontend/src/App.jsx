// Grundgerüst für das Dashboard mit Fokus auf Barrierefreiheit
export const Dashboard = () => (
  <div className="app-container">
    <nav aria-label="Hauptnavigation">
      {/* Navigations-Links */}
    </nav>
    <main id="main-content">
      <section aria-labelledby="metrics-heading">
        <h2 id="metrics-heading">Live Metriken</h2>
        <div aria-live="polite" aria-atomic="true">
          {/* Dynamische Metrik-Updates */}
        </div>
      </section>
      <section aria-labelledby="alerts-heading">
        <h2 id="alerts-heading">Anomalie-Warnungen</h2>
        <div role="alert" aria-live="assertive">
          {/* Kritische Anomalien */}
        </div>
      </section>
    </main>
  </div>
);
