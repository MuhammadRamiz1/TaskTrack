import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityPanel } from "@/components/tasks/detail-panels";

vi.mock("@/lib/api/client", () => ({
  $api: {
    useQuery: () => ({
      isPending: false,
      error: null,
      refetch: vi.fn(),
      data: {
        results: [
          {
            id: "a1",
            verb: "status_changed",
            actor: { full_name: "Mia Test" },
            created_at: new Date().toISOString(),
            data: { from: "IN_PROGRESS", to: "IN_REVIEW", comment: "done" },
          },
        ],
      },
    }),
  },
}));

describe("ActivityPanel", () => {
  it("shows from and to status for status_changed", () => {
    render(<ActivityPanel taskId="t1" />);
    expect(screen.getByText("Mia Test")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("In review")).toBeInTheDocument();
    expect(screen.getByText("“done”")).toBeInTheDocument();
  });
});
