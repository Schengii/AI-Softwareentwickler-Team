import Dashboard from './pages/Dashboard';

// Realer Fund (Team-Retrospektive nach dem taskpulse-Lauf): main.tsx importierte
// `App from './App'`, aber diese Datei existierte nie - der neue Vorab-Import-Check
// (core/verifier/completeness.py) hat das aufgedeckt. App bindet bewusst nur die Dashboard-
// Seite ein (echte, funktionierende Datenanbindung über useChecks()/api/checks.ts, siehe
// docs/adr/0001) - Login/Status-Seiten aus der ADR sind bewusst NICHT mitgebaut, weil dafür
// weder Backend-Endpunkte noch bestehender Code existieren (kein Stub, der nur so aussieht,
// als wäre er fertig).
export default function App() {
  return (
    <>
      <header className="app-header">
        <h1>IncidentPilot</h1>
      </header>
      <main className="app-main">
        <Dashboard />
      </main>
    </>
  );
}
