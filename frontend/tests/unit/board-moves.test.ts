import { describe, expect, it } from "vitest";

import { BOARD_ROWS, canDrop, planDrop } from "@/components/tasks/board-moves";
import type { TaskStatus } from "@/components/tasks/meta";
import type { components } from "@/lib/api/schema";

type BoardCard = components["schemas"]["BoardCard"];
type AllowedMove = components["schemas"]["AllowedMove"];

function card(status: TaskStatus, allowed_moves: AllowedMove[]): BoardCard {
  return { status, allowed_moves } as BoardCard;
}

describe("planDrop", () => {
  it("returns null for same column", () => {
    const c = card("IN_PROGRESS", [{ to_status: "IN_PROGRESS", action: "transition", requires_comment: false }]);
    expect(planDrop(c, "IN_PROGRESS")).toBeNull();
    expect(canDrop(c, "IN_PROGRESS")).toBe(false);
  });

  it("returns null for a move not in allowed_moves", () => {
    const c = card("BACKLOG", [{ to_status: "ASSIGNED", action: "assign", requires_comment: false }]);
    expect(planDrop(c, "COMPLETED")).toBeNull();
    expect(canDrop(c, "COMPLETED")).toBe(false);
  });

  it("maps assign/submit/approve/request_changes", () => {
    const c = card("ASSIGNED", [
      { to_status: "IN_PROGRESS", action: "assign", requires_comment: false },
      { to_status: "IN_REVIEW", action: "submit", requires_comment: false },
      { to_status: "COMPLETED", action: "approve", requires_comment: false },
      { to_status: "REOPENED", action: "request_changes", requires_comment: true },
    ]);
    expect(planDrop(c, "IN_PROGRESS")).toEqual({ kind: "assign" });
    expect(planDrop(c, "IN_REVIEW")).toEqual({ kind: "submit", needsReviewer: false });
    expect(planDrop(c, "COMPLETED")).toEqual({ kind: "approve" });
    expect(planDrop(c, "REOPENED")).toEqual({ kind: "request_changes" });
    expect(canDrop(c, "COMPLETED")).toBe(true);
  });

  it("transition keeps requires_comment", () => {
    const c = card("IN_PROGRESS", [{ to_status: "BLOCKED", action: "transition", requires_comment: true }]);
    expect(planDrop(c, "BLOCKED")).toEqual({ kind: "transition", to: "BLOCKED", needsComment: true });
  });
});

describe("BOARD_ROWS", () => {
  it("covers all 9 statuses once", () => {
    const flat = BOARD_ROWS.flat();
    expect(flat).toHaveLength(9);
    expect(new Set(flat).size).toBe(9);
    expect([...flat].sort()).toEqual(
      [
        "BACKLOG",
        "ASSIGNED",
        "IN_PROGRESS",
        "IN_REVIEW",
        "ON_HOLD",
        "BLOCKED",
        "REOPENED",
        "COMPLETED",
        "CANCELLED",
      ].sort(),
    );
    expect(BOARD_ROWS).toEqual([
      ["BACKLOG", "ASSIGNED", "IN_PROGRESS", "IN_REVIEW", "COMPLETED"],
      ["ON_HOLD", "BLOCKED", "REOPENED", "CANCELLED"],
    ]);
  });
});
