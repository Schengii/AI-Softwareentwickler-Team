import React from 'react';
import { useVehicles } from '../hooks/useVehicles';
import DOMPurify from 'dompurify';

const Dashboard: React.FC = () => {
  const { vehicles, loading, error } = useVehicles();

  if (loading) return <div className="p-8" role="status">Lade Flottendaten...</div>;
  if (error) return <div className="p-8 text-red-700" role="alert">{error}</div>;

  return (
    <div className="p-8 bg-gray-50 min-h-screen">
      <h1 className="text-2xl font-bold mb-6">Flotten-Dashboard</h1>
      <div 
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
        aria-live="polite"
      >
        {vehicles.map((v) => (
          <div key={v.id} className="bg-white p-6 rounded-lg shadow-md border border-gray-200">
            <h2 
              className="font-semibold text-lg"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(v.vin) }}
            />
            <p 
              className="text-gray-700"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(v.model) }}
            />
            <span className={`inline-block px-2 py-1 mt-2 text-xs font-bold rounded ${
              v.status === 'online' ? 'bg-green-700 text-white' : 
              v.status === 'maintenance' ? 'bg-yellow-600 text-white' : 'bg-red-700 text-white'
            }`}>
              {v.status.toUpperCase()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Dashboard;
