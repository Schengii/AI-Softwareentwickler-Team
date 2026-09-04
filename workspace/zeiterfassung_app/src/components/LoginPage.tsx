import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await login(username, password);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Anmeldung fehlgeschlagen. Bitte Zugangsdaten prüfen.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="auth-container">
      <form onSubmit={handleSubmit} className="card-form" aria-labelledby="login-heading">
        <h2 id="login-heading">Zeiterfassung – Login</h2>
        {error && <div className="error-alert" role="alert">{error}</div>}
        <div className="form-group">
          <label htmlFor="username">Benutzername</label>
          <input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoComplete="username"
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Passwort</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>
        <button type="submit" disabled={loading} className="btn-primary">
          {loading ? 'Wird angemeldet...' : 'Anmelden'}
        </button>
      </form>
    </main>
  );
};
