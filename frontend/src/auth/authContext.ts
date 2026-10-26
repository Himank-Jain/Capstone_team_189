import { createContext, useContext } from 'react';
import type { AuthSession, Membership, Role } from '../services/authApi';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  status: AuthStatus;
  session: AuthSession | null;
  activeTenantId: string | null;
  activeMembership: Membership | null;
  /** Role in the active workspace (null when not a member). */
  role: Role | null;
  signIn: (email: string, password: string) => Promise<AuthSession>;
  signUp: (email: string, password: string) => Promise<AuthSession>;
  signOut: () => void;
  switchTenant: (tenantId: string) => void;
  refresh: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}

/** Read-only variant for components that also render outside the provider (tests). */
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}
