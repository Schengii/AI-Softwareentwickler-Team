import { useState, useEffect } from 'react';
import { fetchVehicles } from '../services/api';

export interface Vehicle {
  id: string;
  vin: string;
  model: string;
  status: 'online' | 'offline' | 'maintenance';
}

export const useVehicles = () => {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadVehicles = async () => {
      try {
        const { data } = await fetchVehicles();
        setVehicles(data);
      } catch (err) {
        setError('Fehler beim Laden der Fahrzeuge.');
      } finally {
        setLoading(false);
      }
    };
    loadVehicles();
  }, []);

  return { vehicles, loading, error };
};
