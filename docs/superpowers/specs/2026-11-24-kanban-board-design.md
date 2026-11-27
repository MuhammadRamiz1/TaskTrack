# Kanban board: drag to change status

Date: 2026-11-24

## Intent

Changing a task's status is hard today, and tasks are not easy to see. The team wants a
Trello/GitScrum-style board where a card is dragged to another column to change its status,
and where every move is visible in the task's history.

## Current state

- A board already exists: Tasks page, "Board" tab (`frontend/components/tasks/task-views.tsx`,
  `TaskBoard`), one project at a time, using `@dnd-kit/core`.
- Dragging calls only `POST /api/v1/tasks/{id}/transition/`, which handles MANUAL rules only.
  The main path uses other actions:
  - Backlog to Assigned: assignment (`POST /tasks/{id}/assignees/`)
  - In progress to In review: submit for review (`POST /tasks/{id}/review/submit/`)
  - In review to Completed: approve (`POST /tasks/{id}/review/approve/`)
  - In review to In progress: request changes (`POST /tasks/{id}/review/request-changes/`, comment required)
  So 3 of the 4 main-path drags fail, and the user only learns this after dropping.
- Task history already exists (`TaskActivity`, `GET /tasks/{id}/activity/`, `ActivityPanel`).

## Goals

- Drag a card to any column; the drop runs the correct backend action for that move.
- Workflow rules and role permissions stay exactly as they are.
- Columns the current user cannot move a card to are greyed out while dragging and refuse the drop.
- Every move shows in the task's history: who, old status to new status, when, comment.
- The board is easy to find and read.

## Non-goals

- No custom or manager-defined columns. The board shows the 9 fixed statuses, one column each.
- No new statuses and no changes to the transition rules table.
- No manual card ordering inside a column (no `position` field).

## Anti-goals

- A drop that looks accepted and then fails.
- Any way to bypass the review/approval step or role checks from the board.

## Approaches considered

1. Keep the rules; each drop triggers the matching action (assign, submit, approve, request
   changes, manual transition). Chosen: it is as easy to use as Trello and keeps the review
   step that reports and timers depend on.
2. Loosen the rules so anyone can drag anywhere. Rejected: removes review and role control.
3. Manager-defined columns, either mapped onto statuses or as fully custom statuses.
   Rejected by the user: the board stays on the 9 fixed statuses.

## Design

### Backend

- Board endpoint (`GET /api/v1/tasks/board/`) returns, per card, the moves this user may make:
  `allowed_moves: [{to_status, action, requires_comment}]`, where `action` is one of
  `transition | assign | submit | approve | request_changes`. Built from the same rule checks the
  action endpoints use (`workflow.allowed_targets` plus the ASSIGN/SUBMIT/APPROVE/REQUEST_CHANGES
  rules and their role/reviewer checks), computed without extra queries per card where possible.
- Make sure each action writes a `TaskActivity` row with actor, from status, to status and the
  comment, so the history line can be rendered. Add any that are missing.
- Regenerate `frontend/openapi.json` and `lib/api/schema.d.ts`.

### Frontend board

- No horizontal scrolling. The 9 columns wrap into two rows that fit the screen width:
  - Row 1 (main path): Backlog, Assigned, In progress, In review, Completed.
  - Row 2 (side states): On hold, Blocked, Reopened, Cancelled.
  Columns in a row share the width equally. Columns grow with their cards; the page scrolls
  vertically, with no scroll box inside a column. On small screens columns stack (2 per row,
  then 1). Each header shows the status badge and the card count.
- While dragging, columns not in the card's `allowed_moves` are dimmed and not droppable; the
  current column is neutral.
- On drop, by action:
  - `transition`: move now; if `requires_comment`, ask for the comment first.
  - `assign`: popup to pick one or more assignees, then assign.
  - `submit`: if the task has no reviewer, popup to pick one first; optional note; then submit.
  - `approve`: confirm, optional comment, then approve.
  - `request_changes`: comment required, then request changes.
  - Cancel in a popup leaves the card where it was.
- Optimistic move on drop, rolled back with an error toast if the request fails.
- The mobile "Move to..." select lists only `allowed_moves`.
- Board is the default view on the Tasks page; List and Calendar stay as tabs.

### Cards

- Clear Trello-style card: key, title (2 lines), priority, assignee avatars, due date
  (red when overdue), reviewer avatar when in review, and markers for blocked/needs reassignment.

### History

- On the task page, the Activity panel shows status moves as one line each:
  "<actor> moved <from> to <to> · <relative time>", with the comment underneath when present.

## Builder's calls (not decided by the user)

- Exact card styling and spacing, within the existing design system.
- Whether to show `allowed_moves` reasons (e.g. "only managers can approve") as a tooltip on dimmed columns.
- Test coverage: backend tests for `allowed_moves` per role and per action; frontend tests for drop routing.
