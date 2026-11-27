"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { Logo } from "@/components/auth/auth-shell";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/auth/session";
import { refreshSession } from "@/lib/auth/token";
import { cn } from "@/lib/utils";

import { NotificationBell, UserMenu } from "./header-menus";
import { type NavItem } from "./nav";
import { ThemeToggle } from "./theme-toggle";
import { TimerBar } from "./timer-bar";

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLinks({ items, collapsed, onNavigate }: { items: NavItem[]; collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-1">
      {items.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? label : undefined}
            className={cn(
              "flex min-h-11 items-center gap-3 rounded-xl px-3 text-[14.5px] font-semibold transition-colors",
              active
                ? "bg-primary-600 text-on-primary shadow-button"
                : "text-muted hover:bg-hover hover:text-ink",
              collapsed && "justify-center px-0",
            )}
          >
            <Icon className="size-[18px] shrink-0" aria-hidden />
            {!collapsed && <span className="truncate">{label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

/** The impersonation token is read-only and cannot end itself: restore the super admin's
 * own session from their refresh cookie, end the session with it, and go back. */
async function endImpersonation(sessionId: string) {
  const admin = await refreshSession();
  if (admin?.is_platform_admin) {
    try {
      await api.POST("/api/v1/platform/impersonations/{session_id}/end/", {
        params: { path: { session_id: sessionId } },
      });
    } catch {
      /* already expired: nothing to end */
    }
  }
  // Full reload on purpose: drops the in-memory impersonation token and all cached tenant data.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.href = "/platform/companies";
}

function ImpersonationBanner() {
  const me = useMe();
  if (!me.impersonation) return null;
  const imp = me.impersonation;
  return (
    <div role="alert" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-warning-soft px-4 py-2 text-sm text-warning">
      <strong>Read-only impersonation</strong>
      <span>
        Viewing as {me.full_name}. Session ends {new Date(imp.expires_at).toLocaleTimeString()}.
      </span>
      <button className="font-semibold underline" onClick={() => void endImpersonation(imp.id)}>
        Exit
      </button>
    </div>
  );
}

export function AppShell({ items, children }: { items: NavItem[]; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const pathname = usePathname();
  useEffect(() => {
    try {
      // Browser storage is only readable after mount (server render has no localStorage).
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(localStorage.getItem("tt-sidebar") === "collapsed");
    } catch {
      /* storage unavailable */
    }
  }, []);
  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("tt-sidebar", c ? "open" : "collapsed");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };
  const bottom = items.filter((i) => i.primary).slice(0, 4);

  return (
    <div className="flex min-h-dvh">
      {/* Desktop / tablet sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-linear-to-b from-[var(--tt-sidebar-from)] to-[var(--tt-sidebar-to)] p-3 transition-[width] duration-200 md:flex",
          collapsed ? "w-[76px]" : "w-64",
        )}
      >
        <div className={cn("flex items-center px-1 py-2", collapsed ? "justify-center" : "justify-between")}>
          <Link href="/" aria-label="TaskTrack home">
            <Logo compact={collapsed} />
          </Link>
        </div>
        <div className="mt-4 flex-1 overflow-y-auto">
          <NavLinks items={items} collapsed={collapsed} />
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="self-center"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <ImpersonationBanner />
        <header className="sticky top-0 z-20 flex h-16 items-center gap-2 border-b border-line bg-page/85 px-4 backdrop-blur md:px-6">
          <DialogPrimitive.Root open={drawer} onOpenChange={setDrawer}>
            <DialogPrimitive.Trigger asChild>
              <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                <Menu />
              </Button>
            </DialogPrimitive.Trigger>
            <DialogPrimitive.Portal>
              <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-[#120c26]/45 md:hidden" />
              <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-[82vw] max-w-72 flex-col bg-surface p-4 shadow-card md:hidden">
                <DialogPrimitive.Title className="sr-only">Menu</DialogPrimitive.Title>
                <DialogPrimitive.Description className="sr-only">Navigate TaskTrack</DialogPrimitive.Description>
                <div className="mb-4 flex items-center justify-between">
                  <Logo />
                  <DialogPrimitive.Close asChild>
                    <Button variant="ghost" size="icon" aria-label="Close menu">
                      <X />
                    </Button>
                  </DialogPrimitive.Close>
                </div>
                <NavLinks items={items} onNavigate={() => setDrawer(false)} />
              </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
          </DialogPrimitive.Root>
          <Link href="/" className="md:hidden" aria-label="TaskTrack home">
            <Logo compact />
          </Link>
          <div className="flex-1" />
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />
        </header>
        <TimerBar />
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 pt-5 pb-36 md:px-6 md:pt-7 md:pb-10">
          {children}
        </main>
      </div>

      {/* Phone bottom navigation */}
      <nav
        aria-label="Quick"
        className="fixed inset-x-0 bottom-0 z-30 grid border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        style={{ gridTemplateColumns: `repeat(${bottom.length}, minmax(0, 1fr))` }}
      >
        {bottom.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold",
                active ? "text-primary-600" : "text-muted",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

export function FullScreenLoader() {
  return (
    <div className="grid min-h-dvh place-items-center" aria-busy="true" aria-label="Loading">
      <div className="flex flex-col items-center gap-4">
        <span className="animate-pulse">
          <Logo />
        </span>
      </div>
    </div>
  );
}
