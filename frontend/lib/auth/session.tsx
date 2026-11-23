"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { emitSession, type Me, onSessionChange, readCookie, refreshSession, setAccessToken } from "./token";

type Status = "loading" | "authenticated" | "anonymous";

type SessionContext = {
  status: Status;
  user: Me | null;
  /** True when the user holds the permission at any scope. UI hint only; the API decides. */
  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
  scopeOf: (permission: string) => string[];
  /** Store tokens returned by login / accept-invite / 2FA / change-password. */
  startSession: (access: string, user: Me) => void;
  updateUser: (user: Me) => void;
  logout: (everywhere?: boolean) => Promise<void>;
};

const Ctx = createContext<SessionContext | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const queryClient = useQueryClient();
  const router = useRouter();

  useEffect(() => {
    const off = onSessionChange((me) => {
      setUser(me);
      setStatus(me ? "authenticated" : "anonymous");
    });
    // A hint cookie tells us whether a refresh cookie probably exists.
    if (readCookie("tt_session") === "1") void refreshSession();
    else void Promise.resolve().then(() => setStatus("anonymous"));
    return () => {
      off();
    };
  }, []);

  const startSession = useCallback((access: string, me: Me) => {
    setAccessToken(access);
    emitSession(me);
  }, []);

  const logout = useCallback(
    async (everywhere = false) => {
      const headers = { "X-CSRFToken": readCookie("csrftoken") ?? "" };
      try {
        if (everywhere) {
          const { authFetch } = await import("@/lib/api/client");
          await authFetch(new Request("/api/v1/auth/logout-all/", { method: "POST", headers }));
        }
        await fetch("/api/v1/auth/logout/", { method: "POST", credentials: "same-origin", headers });
      } finally {
        setAccessToken(null);
        emitSession(null);
        queryClient.clear();
        router.replace("/login");
      }
    },
    [queryClient, router],
  );

  const value = useMemo<SessionContext>(() => {
    const perms = (user?.permissions ?? {}) as Record<string, string[]>;
    return {
      status,
      user,
      can: (p) => p in perms,
      canAny: (...ps) => ps.some((p) => p in perms),
      scopeOf: (p) => perms[p] ?? [],
      startSession,
      updateUser: (me) => emitSession(me),
      logout,
    };
  }, [status, user, startSession, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/** The signed-in user; only call below a layout that guarantees authentication. */
export function useMe(): Me {
  const { user } = useSession();
  if (!user) throw new Error("useMe called without a signed-in user");
  return user;
}
