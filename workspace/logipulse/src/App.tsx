import React, { useState } from 'react';

interface Anomaly {
  id: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export const App: React.FC = () => {
  const [anomalies] = useState<Anomaly[]>([]);

  return (
    <main className="min-h-screen p-8 bg-gray-900 text-gray-100">
      <header className="mb-8">
        <h1 className="text-3xl font-bold">LogiPulse Observability Dashboard</h1>
      </header>

      {/* In der Anomalien-Sektion: */}
      <section className="bg-gray-800 p-6 rounded-lg border border-gray-700" aria-live="polite">
        <h2 className="text-xl font-semibold mb-4">Aktuelle Anomalien</h2>
        {anomalies.length === 0 ? (
          <p className="text-gray-500">Keine Anomalien gefunden.</p>
        ) : (
          <ul className="space-y-2">
            {anomalies.map((a) => (
              <li key={a.id} className="p-3 bg-gray-900 rounded border-l-4 border-[#6366F1]">
                <span className="font-bold uppercase text-xs" aria-label={`Schweregrad: ${a.severity}`}>
                  [{a.severity}]
                </span> {a.description}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
};

export default App;
