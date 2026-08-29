"use client";

/**
 * Who is signed in, for the whole app.
 *
 * The client does not decide anything with this — the server refuses what a
 * role may not do, and that refusal is the enforcement. What this is for is not
 * showing a nurse a button that will 403, and putting a real name on the
 * sign-off rather than a hardcoded "nurse.demo".
 */
import {
  createContext, useCallback, useContext, useEffect, useState,
} from "react";
import { api, session, type User } from "@/lib/api";

interface AuthValue {
  user: User | null;
  loading: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthValue>({
  user: null,
  loading: true,
  signIn: async () => {},
  signOut: () => {},
  can: () => false,
});

export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // On mount, ask the server who this token belongs to rather than trusting a
  // decoded copy in the browser. A token can be revoked or expired, and only
  // the server knows.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (session.token) {
          // Ask the server who this token belongs to rather than trusting a
          // decoded copy in the browser. Only the server knows whether it has
          // expired or been revoked.
          const me = await api.me();
          if (!cancelled) setUser(me);
        } else {
          // No token. Auth can be switched off for a projector demo, in which
          // case there is nobody to sign in as and the board should just open.
          // This asks a public endpoint: probing /me without a token answered
          // 401 and put a red error in the console on every single visit.
          const mode = await api.mode();
          if (!mode.auth_enabled && !cancelled) setUser(await api.me());
        }
      } catch {
        session.set(null);   // the sign-in screen renders
      }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    setUser(await api.signIn(username, password));
  }, []);

  const signOut = useCallback(() => {
    api.signOut();
    setUser(null);
  }, []);

  const can = useCallback(
    (permission: string) => !!user?.permissions?.includes(permission),
    [user],
  );

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, can }}>
      {children}
    </AuthContext.Provider>
  );
}
