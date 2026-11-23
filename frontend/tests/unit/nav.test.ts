import { describe, expect, it } from "vitest";

import { APP_NAV, homeFor, PLATFORM_NAV, visibleNav } from "@/components/layout/nav";
import type { Me } from "@/lib/auth/token";

const user = (permissions: Record<string, string[]>, extra: Record<string, unknown> = {}) =>
  ({ permissions, is_platform_admin: false, impersonation: null, ...extra }) as unknown as Me;

describe("role-aware navigation", () => {
  it("shows a team member only their work areas", () => {
    const labels = visibleNav(
      APP_NAV,
      user({ "task.view": ["OWN"], "time.track": ["OWN"], "dashboard.member.view": ["OWN"] }),
    ).map((i) => i.label);
    expect(labels).toEqual(["Dashboard", "My tasks", "Tasks", "Timesheets", "Settings"]);
  });

  it("shows HR people tools but no task screens", () => {
    const labels = visibleNav(
      APP_NAV,
      user({ "employee.create": ["COMPANY"], "team.manage": ["COMPANY"], "audit.view": ["COMPANY"] }),
    ).map((i) => i.label);
    expect(labels).toContain("People");
    expect(labels).toContain("Audit log");
    expect(labels).not.toContain("Tasks");
  });

  it("sends super admins to the platform unless impersonating", () => {
    expect(homeFor(user({}, { is_platform_admin: true }))).toBe("/platform/companies");
    expect(homeFor(user({}, { is_platform_admin: true, impersonation: { id: "x" } }))).toBe("/dashboard");
    expect(PLATFORM_NAV.map((i) => i.href)).toContain("/platform/plans");
  });
});
