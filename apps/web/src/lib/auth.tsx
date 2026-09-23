import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { api } from './api';

type User = { id: string; email: string; display_name: string | null; email_verified: boolean };
type Ctx = { user: User | null; token: string | null; login(e: string, p: string): Promise<void>; register(e: string, p: string, n?: string): Promise<void>; logout(): void };

const AuthCtx = createContext<Ctx>({} as Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('seo.token'));
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!token) { setUser(null); return; }
    api.get<User>('/api/v1/auth/me').then(setUser).catch(() => { localStorage.removeItem('seo.token'); setToken(null); });
  }, [token]);

  const login = async (email: string, password: string) => {
    const r = await api.post<{ access_token: string }>('/api/v1/auth/login', { email, password });
    localStorage.setItem('seo.token', r.access_token);
    setToken(r.access_token);
  };
  const register = async (email: string, password: string, display_name?: string) => {
    await api.post('/api/v1/auth/register', { email, password, display_name });
    await login(email, password);
  };
  const logout = () => { localStorage.removeItem('seo.token'); setToken(null); setUser(null); };

  return <AuthCtx.Provider value={{ user, token, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
