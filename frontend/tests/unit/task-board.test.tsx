import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskBoard } from "@/components/tasks/task-views";
import { ApiError } from "@/lib/api/errors";

const mocks = vi.hoisted(() => ({ post: vi.fn(), patch: vi.fn(), toastError: vi.fn(), toastSuccess: vi.fn() }));

vi.mock("sonner", () => ({ toast: { error: mocks.toastError, success: mocks.toastSuccess } }));

// Refetches after the first never resolve, so only the snapshot restore can put it back in Backlog.
const fetches = { board: 0 };
const STATUS_ORDER = ["BACKLOG", "ASSIGNED", "IN_PROGRESS", "IN_REVIEW", "COMPLETED", "ON_HOLD", "BLOCKED", "REOPENED", "CANCELLED"];

function card(over: Record<string, unknown> = {}) {
  return {
    id: "t1", key: "TT-1", number: 1, title: "Write docs", status: "BACKLOG", priority: "HIGH",
    project: { id: "p1", key: "TT", name: "TaskTrack" }, parent_id: null, due_date: null,
    assignees: [], reviewer: null, needs_reassignment: false, is_read_only: false, is_overdue: false, version: 3,
    checklist_total: 8, checklist_done: 2, comment_count: 1, attachment_count: 0,
    allowed_moves: [
      { to_status: "ASSIGNED", action: "assign", requires_comment: false },
      { to_status: "BLOCKED", action: "transition", requires_comment: true },
      { to_status: "ON_HOLD", action: "transition", requires_comment: false },
    ],
    ...over,
  };
}

function board(cards = [card()]) {
  return {
    project: { id: "p1", key: "TT", name: "TaskTrack" },
    columns: STATUS_ORDER.map((status) => ({ status, tasks: cards.filter((c) => c.status === status) })),
  };
}

function detail() {
  return {
    ...card(), description: "Explain the API", instructions: "", acceptance_criteria: "Reviewed by docs team",
    created_by: { id: "u9", full_name: "Max Boss" }, checklists: [], dependencies: [], dependents: [], subtasks: [],
    allowed_transitions: [],
  };
}

// The modal's comment/attachment/checklist panels are covered elsewhere.
vi.mock("@/components/tasks/detail-panels", () => ({
  ChecklistsPanel: () => null, CommentsPanel: () => null, AttachmentsPanel: () => null,
}));

vi.mock("@/lib/api/client", () => ({
  api: { POST: (...a: unknown[]) => mocks.post(...a), PATCH: (...a: unknown[]) => mocks.patch(...a) },
  $api: {
    useQuery: (method: string, path: string, init: unknown) =>
      useQuery({
        queryKey: [method, path, init],
        queryFn: async () =>
          path === "/api/v1/org/directory/"
            ? { results: [{ id: "u1", full_name: "Ann Lee", email: "ann@x.io", status: "ACTIVE" }] }
            : path === "/api/v1/tasks/{task_id}/"
              ? detail()
              : (fetches.board++ === 0 ? board() : new Promise<never>(() => {})),
      }),
  },
}));

function renderBoard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return render(<TaskBoard projectId="p1" />, { wrapper: wrap });
}

const region = (name: RegExp) => screen.getByRole("region", { name });

afterEach(cleanup);

beforeEach(() => {
  fetches.board = 0;
  mocks.post.mockReset().mockResolvedValue({});
  mocks.patch.mockReset().mockResolvedValue({});
  mocks.toastError.mockReset();
  mocks.toastSuccess.mockReset();
});

describe("TaskBoard", () => {
  it("renders 9 columns in two rows in BOARD_ROWS order", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    const rows = screen.getAllByTestId("board-row");
    expect(rows).toHaveLength(2);
    const names = rows.map((r) => within(r).getAllByRole("region").map((s) => s.getAttribute("aria-label")!.split(",")[0]));
    expect(names[0]).toEqual(["Backlog", "Assigned", "In progress", "In review", "Completed"]);
    expect(names[1]).toEqual(["On hold", "Blocked", "Reopened", "Cancelled"]);
    expect(rows[0].className).toContain("lg:grid-cols-5");
    expect(rows[1].className).toContain("lg:grid-cols-4");
    const html = rows[0].parentElement!.outerHTML;
    for (const bad of ["overflow-x-auto", "snap-x", "-mx-4", "shrink-0", "w-[82vw]", "sm:w-72"]) expect(html).not.toContain(bad);
    expect(region(/^Backlog,/).className).toContain("min-w-0");
  });

  it("dims columns not in allowed_moves while dragging", async () => {
    renderBoard();
    const handle = await screen.findByRole("button", { name: /TT-1 Write docs/ });
    fireEvent.keyDown(handle, { code: "Space", key: " " });
    await waitFor(() => expect(region(/^In progress,/).className).toContain("opacity-40"));
    expect(region(/^Assigned,/).className).not.toContain("opacity-40");
    expect(region(/^Blocked,/).className).not.toContain("opacity-40");
    expect(region(/^Backlog,/).className).not.toContain("opacity-40");
  });

  it("opens assignee dialog when dropping on Assigned", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.change(screen.getByLabelText("Move TT-1 to"), { target: { value: "ASSIGNED" } });
    expect(await screen.findByRole("dialog", { name: /Assign TT-1/ })).toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: /Ann Lee/ }));
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/v1/tasks/{task_id}/assignees/", {
        params: { path: { task_id: "t1" } }, body: { user_ids: ["u1"] },
      }),
    );
  });

  it("asks for a comment when moving to Blocked", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.change(screen.getByLabelText("Move TT-1 to"), { target: { value: "BLOCKED" } });
    const dialog = await screen.findByRole("dialog");
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "waiting on vendor" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move task" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/v1/tasks/{task_id}/transition/", {
        params: { path: { task_id: "t1" } }, body: { to_status: "BLOCKED", comment: "waiting on vendor", version: 3 },
      }),
    );
  });

  it("moves at once when no input is needed and cancel leaves the card in place", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.change(screen.getByLabelText("Move TT-1 to"), { target: { value: "BLOCKED" } });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(within(region(/^Backlog,/)).getByText("Write docs")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Move TT-1 to"), { target: { value: "ON_HOLD" } });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  });

  it("rolls back card when move fails", async () => {
    let reject!: (e: unknown) => void;
    mocks.post.mockReturnValue(new Promise((_, r) => { reject = r; }));
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.change(screen.getByLabelText("Move TT-1 to"), { target: { value: "ON_HOLD" } });
    await waitFor(() => expect(within(region(/^On hold,/)).getByText("Write docs")).toBeInTheDocument());
    reject(new ApiError(409, { error: { code: "version_conflict", message: "Task changed" } }));
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith("Task changed"));
    await waitFor(() => expect(within(region(/^Backlog,/)).getByText("Write docs")).toBeInTheDocument());
  });

  it("shows checklist progress and counts on the card", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    expect(screen.getByText("25% completed")).toBeInTheDocument();
    expect(screen.getByText("2/8")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "TT-1 checklist" })).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByLabelText("1 comment")).toBeInTheDocument();
    expect(screen.queryByLabelText(/attachments/)).not.toBeInTheDocument();
  });

  it("opens the task details modal when the card is clicked", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.click(screen.getByText("TT-1"));
    const dialog = await screen.findByRole("dialog", { name: "Write docs" });
    expect(await within(dialog).findByText("Explain the API")).toBeInTheDocument();
    expect(within(dialog).getByText("Reviewed by docs team")).toBeInTheDocument();
    expect(within(dialog).getByText("Max Boss")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Open full page/ })).toHaveAttribute("href", "/tasks/t1");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("does not open the modal from the move-to select", async () => {
    renderBoard();
    await screen.findByText("Write docs");
    fireEvent.click(screen.getByLabelText("Move TT-1 to"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
