import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor für Idempotency
apiClient.interceptors.request.use((config) => {
  if (['post', 'patch', 'put'].includes(config.method || '')) {
    config.headers['X-Idempotency-Key'] = crypto.randomUUID();
  }
  return config;
});

export const moveCard = async (cardId: number, columnId: number, position: number) => {
  return apiClient.patch(`/cards/${cardId}/move`, { column_id: columnId, position });
};

export default apiClient;
