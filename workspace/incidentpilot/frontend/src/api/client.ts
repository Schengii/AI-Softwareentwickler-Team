import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'https://api.incidentpilot.local/v1',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      if (error.response.status === 401) {
        window.location.href = '/login';
      } else if (error.response.status >= 500) {
        console.error('Server Error:', error.response.data);
        // Hier könnte ein Toast-Service aufgerufen werden
      }
    }
    return Promise.reject(error);
  }
);

export default api;
