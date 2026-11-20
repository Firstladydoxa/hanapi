"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type User } from "./api";

interface AuthState { user: User | null; loading: boolean; signOut: () => Promise<void>; setUser: (u: User) => void }
const Ctx = createContext<AuthState>({ user: null, loading: true, signOut: async () => undefined, setUser: () => undefined });

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.me()
      .then((s) => { if (!cancelled) setUser(s.user); })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [router]);

  const signOut = useCallback(async () => {
    try { await api.logout(); } finally { router.replace("/login"); }
  }, [router]);

  const value = useMemo(() => ({ user, loading, signOut, setUser }), [user, loading, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = (): AuthState => useContext(Ctx);

/**
 * Convenience only: these helpers decide which links are SHOWN. The backend is the real access control and
 * rejects every request the user is not permitted to make.
 */
export const canSeeAdmin = (u: User | null): boolean => !!u && (u.role === "tni_admin" || u.role === "technical_admin");
export const canSeeOps = (u: User | null): boolean => !!u && (u.role === "technical_admin" || u.role === "tni_admin");
export const canSeeAudit = (u: User | null): boolean => !!u && ["auditor", "tni_admin", "technical_admin"].includes(u.role);
