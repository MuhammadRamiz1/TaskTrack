import type { components } from "@/lib/api/schema";

import type { TaskStatus } from "./meta";

type BoardCard = components["schemas"]["BoardCard"];

/** Kanban rows, left to right. Row 1 and row 2 together cover all nine statuses. */
export const BOARD_ROWS: TaskStatus[][] = [
  ["BACKLOG", "ASSIGNED", "IN_PROGRESS", "IN_REVIEW", "COMPLETED"],
  ["ON_HOLD", "BLOCKED", "REOPENED", "CANCELLED"],
];

export type DropPlan =
  | { kind: "transition"; to: TaskStatus; needsComment: boolean }
  | { kind: "assign" }
  | { kind: "submit"; needsReviewer: boolean }
  | { kind: "approve" }
  | { kind: "request_changes" };

/**
 * Resolves what dropping `card` on column `to` should do, based only on the
 * server-provided `allowed_moves`. Returns null when the drop is a no-op or
 * the move is not allowed.
 */
export function planDrop(card: BoardCard, to: TaskStatus): DropPlan | null {
  if (card.status === to) return null;
  const move = card.allowed_moves.find((m) => m.to_status === to);
  if (!move) return null;
  switch (move.action) {
    case "transition":
      return { kind: "transition", to, needsComment: move.requires_comment };
    case "assign":
      return { kind: "assign" };
    // The board card carries no created_by, so the reviewer picker is opened
    // by the submit endpoint's reviewer_required error instead (Task 3).
    case "submit":
      return { kind: "submit", needsReviewer: false };
    case "approve":
      return { kind: "approve" };
    case "request_changes":
      return { kind: "request_changes" };
  }
}

export function canDrop(card: BoardCard, to: TaskStatus): boolean {
  return planDrop(card, to) !== null;
}
