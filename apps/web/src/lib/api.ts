// Single place that knows the backend URL.
// Web: VITE_API_URL. Desktop (Tauri): stored backend URL from Settings, fallback to VITE_API_URL.
const LS_KEY = 'seo.backendUrl';

export function getBackendUrl(): string {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(LS_KEY) : null;
  if (stored && /^https?:\/\//.test(stored)) return stored.replace(/\/$/, '');
  const env = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL;
  return (env || 'http://localhost:8000').replace(/\/$/, '');
}

export function setBackendUrl(url: string) {
  localStorage.setItem(LS_KEY, url.replace(/\/$/, ''));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('seo.token');
  const res = await fetch(`${getBackendUrl()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = (data as { error?: { message?: string }; detail?: string })?.error?.message
      ?? (data as { detail?: string })?.detail
      ?? `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) => request<T>(p, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  patch: <T,>(p: string, body?: unknown) => request<T>(p, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  del: <T,>(p: string) => request<T>(p, { method: 'DELETE' }),
};

export type { };
