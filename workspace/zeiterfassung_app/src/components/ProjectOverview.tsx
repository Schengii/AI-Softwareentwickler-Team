import React, { useEffect, useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { Project, TimeEntry } from '../types';
import { TimeEntryForm } from './TimeEntryForm';

export const ProjectOverview: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = async () => {
    try {
      const res = await apiClient.get<Project[]>('/projects');
      setProjects(res.data);
      if (res.data.length > 0 && !selectedProjectId) {
        setSelectedProjectId(res.data[0].id);
      }
    } catch (err: any) {
      setError('Fehler beim Laden der Projekte.');
    } finally {
      setLoading(false);
    }
  };

  const fetchEntries = useCallback(async (projectId: string) => {
    try {
      const res = await apiClient.get<TimeEntry[]>(`/projects/${projectId}/time-entries`);
      setEntries(res.data);
    } catch (err) {
      setError('Fehler beim Laden der Zeiteinträge.');
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      fetchEntries(selectedProjectId);
    }
  }, [selectedProjectId, fetchEntries]);

  if (loading) return <div>Lade Projektdaten...</div>;

  const currentProject = projects.find((p) => p.id === selectedProjectId);

  const calculateHours = (start: string, end: string) => {
    const diffMs = new Date(end).getTime() - new Date(start).getTime();
    return (diffMs / (1000 * 60 * 60)).toFixed(2);
  };

  return (
    <div className="dashboard-container">
      <h2>Projektübersicht</h2>
      {error && <div className="error-alert">{error}</div>}

      {projects.length > 0 && (
        <TimeEntryForm projects={projects} onEntryAdded={() => selectedProjectId && fetchEntries(selectedProjectId)} />
      )}

      <div className="project-tabs">
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelectedProjectId(p.id)}
            className={`tab-btn ${p.id === selectedProjectId ? 'active' : ''}`}
          >
            {p.name}
          </button>
        ))}
      </div>

      {currentProject && (
        <section className="entries-list">
          <h4>Erfasste Zeiten für {currentProject.name} (Stundensatz: {currentProject.hourly_rate} €)</h4>
          <table>
            <thead>
              <tr>
                <th>Datum</th>
                <th>Dauer (Stunden)</th>
                <th>Beschreibung</th>
                <th>Umsatz (€)</th>
              </tr>
            </thead>
            <tbody>
              {entries.length === 0 ? (
                <tr><td colSpan={4}>Bisher keine Zeiteinträge vorhanden.</td></tr>
              ) : (
                entries.map((entry) => {
                  const hours = parseFloat(calculateHours(entry.start, entry.end));
                  const totalAmount = (hours * currentProject.hourly_rate).toFixed(2);
                  return (
                    <tr key={entry.id}>
                      <td>{new Date(entry.start).toLocaleDateString()}</td>
                      <td>{hours} h</td>
                      <td>{entry.description}</td>
                      <td>{totalAmount} €</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
};
