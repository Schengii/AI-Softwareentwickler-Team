    // Implementierung nach Vorgabe Accessibility-Spezialist
    export const App = () => (
      <>
        <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 p-4 bg-white">
          Zum Hauptinhalt springen
        </a>
        <header role="banner"><nav aria-label="Hauptnavigation">...</nav></header>
        <main id="main-content" role="main"><h1>Governance-Plattform</h1></main>
      </>
    );
    