import React, { useState, useEffect } from 'react';

interface Secret {
  id: string;
  key: string;
  version: number;
  environment: string;
}

const Dashboard: React.FC = () => {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSecrets = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/v1/secrets', {
        headers: { 'X-Vault-User-ID': 'admin' }
      });
      if (!response.ok) throw new Error('Fehler beim Laden der Secrets');
      const data = await response.json();
      setSecrets(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSecrets(); }, []);

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>VaultGuard Dashboard</h1>
      
      <div aria-live="polite">
        {loading && <p>Daten werden geladen...</p>}
        {error && (
          <section aria-labelledby="error-heading">
            <h2 id="error-heading" style={{ color: '#d32f2f' }}>Fehler</h2>
            <p>{error}</p>
            <button onClick={fetchSecrets}>Erneut versuchen</button>
          </section>
        )}
      </div>

      {!loading && !error && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
          <caption>Liste der gespeicherten Secrets</caption>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '2px solid #333' }}>
              <th scope="col" style={{ padding: '0.5rem' }}>Key</th>
              <th scope="col" style={{ padding: '0.5rem' }}>Version</th>
              <th scope="col" style={{ padding: '0.5rem' }}>Environment</th>
            </tr>
          </thead>
          <tbody>
            {secrets.map(s => (
              <tr key={s.id} style={{ borderBottom: '1px solid #ccc' }}>
                <td style={{ padding: '0.5rem' }}>{s.key}</td>
                <td style={{ padding: '0.5rem' }}>{s.version}</td>
                <td style={{ padding: '0.5rem' }}>{s.environment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
};

export default Dashboard;
