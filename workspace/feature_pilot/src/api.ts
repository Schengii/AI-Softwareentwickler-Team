import type { Item, ItemPayload, User } from './types';

const API_BASE = (import.meta.env.VITE_API_URL ?? '/api/v1').replace(/\/$/, '');

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('feature_pilot_token');
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
    });
    if (!response.ok) {
      let message = `Die Anfrage ist fehlgeschlagen (${response.status}).`;
      try { const body = await response.json(); message = body.detail ?? message; } catch { /* Nicht jede API liefert JSON-Fehler. */ }
      throw new ApiError(message, response.status);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('Die Anfrage hat zu lange gedauert.');
    throw new Error('Server nicht erreichbar. Bitte prüfe deine Verbindung.');
  } finally { window.clearTimeout(timeout); }
}

export const api = {
  async login(email: string, password: string): Promise<string> {
    const body = new URLSearchParams({ username: email, password });
    const response = await request<{ access_token: string }>('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body });
    localStorage.setItem('feature_pilot_token', response.access_token);
    return response.access_token;
  },
  me: () => request<User>('/users/me'),
  listItems: () => request<Item[]>('/items'),
  createItem: (payload: ItemPayload) => request<Item>('/items', { method: 'POST', body: JSON.stringify(payload) }),
  updateItem: (id: number, payload: ItemPayload) => request<Item>(`/items/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteItem: (id: number) => request<void>(`/items/${id}`, { method: 'DELETE' }),
};

export function clearSession(): void { localStorage.removeItem('feature_pilot_token'); }
export function isAuthenticated(): boolean { return Boolean(localStorage.getItem('feature_pilot_token')); }
