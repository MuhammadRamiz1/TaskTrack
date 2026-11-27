import {
  BarChart3,
  Building2,
  CheckSquare,
  ClipboardCheck,
  CreditCard,
  FileSearch,
  LayoutDashboard,
  ListTodo,
  type LucideIcon,
  Network,
  Settings,
  Users,
} from "lucide-react";

import type { Me } from "@/lib/auth/token";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown when the user holds any of these permissions (UI hint; the API enforces). */
  anyOf?: string[];
  /** Included in the phone bottom bar. */
  primary?: boolean;
};

export const APP_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, primary: true,
    anyOf: ["dashboard.manager.view", "dashboard.member.view", "employee.create"] },
  { href: "/my-tasks", label: "My tasks", icon: CheckSquare, anyOf: ["time.track"], primary: true },
  { href: "/tasks", label: "Tasks", icon: ListTodo, anyOf: ["task.view"], primary: true },
  { href: "/reviews", label: "Reviews", icon: ClipboardCheck, anyOf: ["review.decide"] },
  { href: "/reports", label: "Reports", icon: BarChart3, anyOf: ["report.view"] },
  { href: "/hr/employees", label: "People", icon: Users, anyOf: ["employee.create", "employee.assign_role"] },
  { href: "/hr/org", label: "Organization", icon: Network, anyOf: ["team.manage", "project.manage", "leave.manage"] },
  { href: "/audit", label: "Audit log", icon: FileSearch, anyOf: ["audit.view"] },
  { href: "/settings", label: "Settings", icon: Settings },
];

export const PLATFORM_NAV: NavItem[] = [
  { href: "/platform/companies", label: "Companies", icon: Building2, primary: true },
  { href: "/platform/plans", label: "Plans", icon: CreditCard, primary: true },
  { href: "/platform/audit", label: "Audit log", icon: FileSearch, primary: true },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function visibleNav(items: NavItem[], me: Me): NavItem[] {
  const perms = (me.permissions ?? {}) as Record<string, string[]>;
  return items.filter((i) => !i.anyOf || i.anyOf.some((p) => p in perms));
}

export function homeFor(me: Me): string {
  if (me.is_platform_admin && !me.impersonation) return "/platform/companies";
  return "/dashboard";
}
