import React, { useState } from 'react';
import { apiClient } from '../api/client';
import { Project } from '../types';

interface TimeEntryFormProps {
  projects: Project[];
  onEntryAdded: () => void;
}

export const TimeEntryForm: React.FC<TimeEntryFormProps> = ({ projects, onEntryAdded }) => {
  const [projectId, setProjectId] = useState(projects[0]?.id || '');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (new Date(end) <= new Date(start)) {
      setError('Das Enddatum muss nach dem Startdatum liegen.');
      return;
    }

    setLoading(true);
    try {
      await apiClient.post('/time-entries', {
        project_id: projectId,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        description,
      });
      setStart('');
      setEnd('');
      setDescription('');
      onEntryAdded();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Fehler beim Speichern des Zeiteintrags.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="card-section">
      <h3>Neuen Zeiteintrag erfassen</h3>
      {error && <div className="error-alert" role="alert">{error}</div>}
      <form onSubmit={handleSubmit} className="form-grid">
        <div className="form-group">
          <label htmlFor="project-select">Projekt</label>
          <select
            id="project-select"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            required
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name} ({p.client_name})</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="start-time">Startzeit</label>
          <input
            id="start-time"
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="end-time">Endzeit</label>
          <input
            id="end-time"
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            required
          />
        </div>

        <div className="form-group full-width">
          <label htmlFor="description">Beschreibung / Tätigkeit</label>
          <input
            id="description"
            type="text"
            placeholder="z.B. Frontend-Entwicklung & Code Review"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>

        <button type="submit" disabled={loading} className="btn-success">
          {loading ? 'Speichere...' : 'Zeiteintrag buchen'}
        </button>
      </form>
    </section>
  );
};
