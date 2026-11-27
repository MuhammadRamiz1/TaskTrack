import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuditTable } from "@/components/common/audit-table";

const entry = {
  id: "a1", created_at: "2026-11-27T10:00:00Z", company_id: "c", actor_id: "u", actor_email: "hana@x.io",
  impersonator_id: null, action: "org.team.members_added",
  summary: "Hana Test added Mo Test and Mia Test to the team Web.",
  changes: [{ field: "Name", before: "Web", after: "Web apps" }],
  entity_type: "team", entity_id: "t", old_value: { name: "Web" }, new_value: { user_ids: ["u1"] },
  ip: "10.0.0.1", user_agent: "", request_id: "",
};

vi.mock("@/lib/api/client", () => ({
  $api: { useQuery: () => ({ data: { count: 1, results: [entry] }, isPending: false, error: null, refetch: vi.fn() }) },
}));

afterEach(cleanup);

describe("AuditTable", () => {
  it("shows a sentence and readable changes to company readers, never codes", () => {
    const { container } = render(<AuditTable />);
    expect(screen.getAllByText("Hana Test added Mo Test and Mia Test to the team Web.").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: /1 change/ })[0]);
    expect(screen.getAllByText("Web apps").length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("org.team.members_added");
    expect(container.textContent).not.toContain("user_ids");
  });

  it("lets platform admins see the action code and raw record", () => {
    render(<AuditTable platform />);
    expect(screen.getAllByText("org.team.members_added").length).toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: /1 change/ })[0]);
    expect(screen.getAllByText(/"user_ids"/).length).toBeGreaterThan(0);
  });
});
