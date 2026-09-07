const BASE_URL = '/api/v1';

async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  retries = 3,
  backoff = 300
): Promise<Response> {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${BASE_URL}${url}`, { ...options, headers });

    if (response.status === 429 && retries > 0) {
      await new Promise((resolve) => setTimeout(resolve, backoff));
      return fetchWithRetry(url, options, retries - 1, backoff * 2);
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Unbekannter Serverfehler' }));
      throw new Error(errorData.detail || `Fehler HTTP ${response.status}`);
    }

    return response;
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error('Netzwerkfehler: Server nicht erreichbar.');
    }
    throw error;
  }
}

export const api = {
  get: <T>(url: string): Promise<T> =>
    fetchWithRetry(url).then((res) => res.json()),
  
  post: <T>(url: string, body: unknown): Promise<T> =>
    fetchWithRetry(url, { method: 'POST', body: JSON.stringify(body) }).then((res) => res.json()),

  put: <T>(url: string, body: unknown): Promise<T> =>
    fetchWithRetry(url, { method: 'PUT', body: JSON.stringify(body) }).then((res) => res.json()),

  delete: <T>(url: string): Promise<T> =>
    fetchWithRetry(url, { method: 'DELETE' }).then((res) => res.json()),
};
