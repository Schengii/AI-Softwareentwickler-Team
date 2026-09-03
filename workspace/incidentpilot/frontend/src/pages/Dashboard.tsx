import { type FormEvent, useState } from 'react';

import { useChecks } from '../hooks/useChecks';

const DEFAULT_INTERVAL_SECONDS = 60;

export default function Dashboard() {
  const { checks, loading, error, addCheck } = useChecks();
  const [url, setUrl] = useState('');
  const [intervalSeconds, setIntervalSeconds] = useState(String(DEFAULT_INTERVAL_SECONDS));
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!url.trim()) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await addCheck({ url: url.trim(), interval_seconds: Number(intervalSeconds) || DEFAULT_INTERVAL_SECONDS });
      setUrl('');
      setIntervalSeconds(String(DEFAULT_INTERVAL_SECONDS));
    } catch {
      setSubmitError('Check konnte nicht angelegt werden.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section>
      <form className="check-form" onSubmit={handleSubmit}>
        <label htmlFor="check-url">URL</label>
        <input
          id="check-url"
          type="url"
          placeholder="https://example.com"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          required
        />
        <label htmlFor="check-interval">Intervall (Sekunden)</label>
        <input
          id="check-interval"
          type="number"
          min={10}
          value={intervalSeconds}
          onChange={(event) => setIntervalSeconds(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? 'Wird angelegt…' : 'Check anlegen'}
        </button>
      </form>

      {submitError && <div className="error-banner">{submitError}</div>}
      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <p>Lade Checks…</p>
      ) : checks.length === 0 ? (
        <p className="empty-state">Noch keine Uptime-Checks angelegt.</p>
      ) : (
        <ul className="check-list">
          {checks.map((check) => (
            <li key={check.id} className="check-item">
              <span>{check.url}</span>
              <span>{check.interval_seconds}s</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
