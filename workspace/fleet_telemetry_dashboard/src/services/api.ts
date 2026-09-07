import axios from 'axios';

const API_BASE = '/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Fehlerbehandlung mit exponentiellem Backoff-Ansatz (vereinfacht)
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 429) {
      // Hier könnte ein Retry-Mechanismus implementiert werden
      console.warn('Rate limit exceeded');
    }
    return Promise.reject(error);
  }
);

export const fetchVehicles = () => apiClient.get('/vehicles');
export const fetchTelemetry = (vehicleId: string) => apiClient.get(`/telemetry/${vehicleId}`);
export const fetchDiagnostics = (vehicleId: string) => apiClient.get(`/diagnostics/${vehicleId}`);
