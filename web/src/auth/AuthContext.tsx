import { useCallback, useMemo, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import * as api from '../api/client';
import { session } from './session';
import { AuthContext } from './context';
import type { AuthContextValue } from './context';
import { useAuth } from './useAuth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const current = useSyncExternalStore(session.subscribe, session.get, session.get);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login({ email, password });
    session.set({ token: result.access_token, admin: result.admin });
  }, []);

  const logout = useCallback(() => {
    session.clear();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ session: current, login, logout }),
    [current, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Redirects to /login when there is no session, remembering where the admin was going. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session: current } = useAuth();
  const location = useLocation();
  if (!current) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
