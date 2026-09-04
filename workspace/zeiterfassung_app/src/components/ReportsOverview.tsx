import React, { useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import { ReportSummary } from '../types';

/**
 * Komponente zur Anzeige der Umsatz- und Zeitübersicht.
 * Nutzt den API-Endpunkt /api/v1/reports/summary.
 */
const ReportsOverview: React.FC = () => {
  const [data, setData] = useState<ReportSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchSummary = async () => {
      try {
        setLoading(true);
        const response = await apiClient.get<ReportSummary>('/reports/summary');
        setData(response.data);
      } catch (err: any) {
        console.error('Fehler beim Abrufen der Reports:', err);
        setError(err.response?.data?.detail || 'Fehler beim Laden der Berichtsdaten.');
      } finally {
        setLoading(false);
      }
    };

    fetchSummary();
  }, []);

  if (loading) return <div className="p-4">Lade Berichtsdaten...</div>;
  if (error) return <div className="p-4 text-red-500">Fehler: {error}</div>;

  return (
    <div className="bg-white p-6 rounded-lg shadow-md">
      <h2 className="text-xl font-bold mb-4">Berichtsübersicht</h2>
      <div className="grid grid-cols-2 gap-4">
        <div className="p-4 bg-blue-50 rounded">
          <p className="text-sm text-gray-600">Gesamtumsatz</p>
          <p className="text-2xl font-semibold">{data?.total_revenue.toFixed(2)} €</p>
        </div>
        <div className="p-4 bg-green-50 rounded">
          <p className="text-sm text-gray-600">Gesamtdauer</p>
          <p className="text-2xl font-semibold">{data?.total_duration_hours.toFixed(1)} Std.</p>
        </div>
      </div>
    </div>
  );
};

export default ReportsOverview;
