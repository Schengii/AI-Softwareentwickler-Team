import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = (globalThis as any).process?.env?.REACT_APP_API_URL || 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 10000,
});

// Request Interceptor: JWT aus localStorage anfügen
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response Interceptor: Exponential Backoff bei HTTP 429
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as InternalAxiosRequestConfig & { _retryCount?: number };
    
    if (error.response?.status === 429 && config) {
      config._retryCount = config._retryCount || 0;
      if (config._retryCount < 3) {
        config._retryCount += 1;
        const delay = Math.pow(2, config._retryCount) * 1000;
        await new Promise((resolve) => setTimeout(resolve, delay));
        return apiClient(config);
      }
    }
    return Promise.reject(error);
  }
);
