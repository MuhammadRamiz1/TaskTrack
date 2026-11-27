"use client";

import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { useSession } from "@/lib/auth/session";
import type { Me } from "@/lib/auth/token";

import { AppShell, FullScreenLoader } from "./app-shell";
import { APP_NAV, homeFor, PLATFORM_NAV, visibleNav } from "./nav";

const SECURITY = "/settings/security";

/** Where a signed-in user must go before anything else (null = stay). */
function forcedRedirect(me: Me, pathname: string, area: "app" | "platform"): string | null {
  if ((me.must_change_password || me.mfa_enrolment_required) && pathname !== SECURITY) return SECURITY;
  const platformUser = me.is_platform_admin && !me.impersonation;
  if (area === "app" && platformUser && !pathname.startsWith("/settings")) return "/platform/companies";
  if (area === "platform" && !platformUser) return homeFor(me);
  return null;
}

export function Guarded({ area, children }: { area: "app" | "platform"; children: ReactNode }) {
  const { status, user } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const target = user ? forcedRedirect(user, pathname, area) : null;

  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (target) router.replace(target);
  }, [status, target, router, pathname]);

  if (status !== "authenticated" || !user || target) return <FullScreenLoader />;
  const platformUser = user.is_platform_admin && !user.impersonation;
  const items = visibleNav(platformUser ? PLATFORM_NAV : APP_NAV, user);
  return <AppShell items={items}>{children}</AppShell>;
}

/** Hides children unless the user holds one of the permissions (UI only; the API enforces). */
export function Can({ anyOf, children, fallback = null }: { anyOf: string[]; children: ReactNode; fallback?: ReactNode }) {
  const { canAny } = useSession();
  return <>{canAny(...anyOf) ? children : fallback}</>;
}
