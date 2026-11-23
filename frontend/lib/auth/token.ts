/**
 * Access token lives only in memory (never localStorage), so XSS cannot read a
 * long-lived credential. The refresh token is an httpOnly cookie the JS never sees.
 */
import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeOutput"];

type Listener = (me: Me | null) => void;

let accessToken: string | null = null;
let refreshing: Promise<Me | null> | null = null;
const listeners = new Set<Listener>();

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function onSessionChange(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emitSession(me: Me | null) {
  listeners.forEach((l) => l(me));
}

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

/**
 * Exchange the refresh cookie for a new access token. Concurrent callers share one
 * request, so a burst of 401s triggers a single refresh.
 */
export function refreshSession(): Promise<Me | null> {
  refreshing ??= (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": readCookie("csrftoken") ?? "" },
      });
      if (!res.ok) {
        setAccessToken(null);
        emitSession(null);
        return null;
      }
      const body = (await res.json()) as { access: string; user: Me };
      setAccessToken(body.access);
      emitSession(body.user);
      return body.user;
    } catch {
      setAccessToken(null);
      emitSession(null);
      return null;
    } finally {
      // Callers that arrived while this request was in flight already share it;
      // anything later must not reuse a finished (possibly stale) result.
      refreshing = null;
    }
  })();
  return refreshing;
}
