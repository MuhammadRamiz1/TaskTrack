import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Optimistic routing only. `tt_session` is a non-secret hint cookie set next to the
 * httpOnly refresh cookie; it decides whether to send people to /login. Real
 * authorisation happens on every API call.
 */
const PUBLIC_PATHS = ["/login", "/accept-invite", "/forgot-password", "/reset-password"];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const hasSession = request.cookies.get("tt_session")?.value === "1";

  if (!isPublic && !hasSession) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }
  if (pathname === "/login" && hasSession) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Skip the API proxy, Next internals and static files.
  matcher: ["/((?!api/|_next/|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp|ico|txt)$).*)"],
};
