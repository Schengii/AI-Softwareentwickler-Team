    // Empfohlene Struktur für frontend/src/api/client.ts
    import axios from 'axios';

    const apiClient = axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL,
      timeout: 10000,
    });

    apiClient.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) { /* Trigger Logout */ }
        console.error('API Error:', error);
        return Promise.reject(error);
      }
    );
    export default apiClient;
    