# Kanban Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drag a task card to any status column on the board; the drop runs the right workflow action, disallowed columns are dimmed, and every move shows in the task's history.

**Architecture:** The backend board endpoint adds `allowed_moves` to each card, computed from the existing transition rules and the same permission checks the assign/review/transition endpoints use. The frontend maps a drop to one of five actions through a pure function, opens a small dialog when the action needs input, and calls the existing endpoints. No new statuses, rules or endpoints for actions.

**Tech Stack:** Django + DRF + drf-spectacular, pytest; Next.js, TanStack Query via `openapi-react-query` (`$api`), `@dnd-kit/core`, Tailwind, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-11-24-kanban-board-design.md`

## Global Constraints

- Statuses stay the 9 fixed values in `apps.tasks.models.Status`; no new statuses, no rule-table changes.
- All status changes still go through `tasks.workflow.transition_task` (directly or via `assignment.assign`, `reviews.services.submit/approve/request_changes`).
- Board columns: row 1 `BACKLOG, ASSIGNED, IN_PROGRESS, IN_REVIEW, COMPLETED`; row 2 `ON_HOLD, BLOCKED, REOPENED, CANCELLED`. No horizontal scroll; no scroll box inside a column.
- No manual card ordering within a column.
- After any backend serializer change: `make api-client` (regenerates `frontend/openapi.json` and `frontend/lib/api/schema.d.ts`); both must be committed.
- Backend checks: `uv run ruff check . && uv run ruff format --check .` in `backend/`. Frontend: `npm run lint && npm run typecheck && npm test` in `frontend/`.

## Review Focus

1. Task with no reviewer and the creator as fallback reviewer: `effective_reviewer_id` is `reviewer_id or created_by_id`, so "In review" is allowed without a popup when the fallback is an active user. Test: `test_submit_allowed_when_creator_is_fallback_reviewer` (Task 1).
2. Reviewer who is also an assignee must not see "Completed" as allowed (self-review). Test: `test_self_review_blocks_approve_move` (Task 1).
3. Locked task (Completed, `locked_at` set): only manual Reopened for Admin/Manager; Team Member sees no moves. Test: `test_completed_task_moves_by_role` (Task 1).
4. Two users move the same card: stale `version` returns `version_conflict`; the board must roll the card back and refetch. Test: `rolls back card when move fails` (Task 3).
5. Board with many tasks must not run per-card rule queries. Test: `test_board_query_count_is_constant` (Task 1).

---

### Task 1: Backend `allowed_moves` on board cards

**Files:**
- Create: `backend/apps/tasks/board.py`
- Modify: `backend/apps/reviews/services.py` (extract `can_decide`, use it inside `_decide`)
- Modify: `backend/apps/tasks/serializers.py` (add `BoardCard`, `AllowedMove`; `BoardOutput` columns use `BoardCard`)
- Modify: `backend/apps/tasks/views.py:215-242` (`TaskBoardView`)
- Modify: `frontend/openapi.json`, `frontend/lib/api/schema.d.ts` (generated)
- Test: `backend/tests/test_board.py`

**Interfaces:**
- Produces: `apps.tasks.board.allowed_moves(actor, task, *, rules: list[StatusTransitionRule]) -> list[dict]`, each dict `{"to_status": str, "action": "transition" | "assign" | "submit" | "approve" | "request_changes", "requires_comment": bool}`, at most one entry per `to_status`, sorted by the `Status` order.
- Produces: `apps.reviews.services.can_decide(actor, task, review) -> bool` (True when the actor passes `review.decide`, is the review's reviewer or company-wide reviewer, and is not blocked by the self-review rule).
- Produces API: `GET /api/v1/tasks/board/` → `columns[].tasks[]` are `BoardCard` = all `TaskSummary` fields + `allowed_moves: AllowedMove[]`.

Rule-to-action mapping (only active rules whose `from_status == task.status`):

| trigger | action | extra check besides role in `rule.allowed_roles` |
|---|---|---|
| MANUAL | `transition` | existing `workflow._actor_allowed`; none if `task.locked_at` and status != COMPLETED |
| ASSIGN | `assign` | `policy.can(actor, "task.assign", task)` |
| SUBMIT | `submit` | `policy.can(actor, "review.submit", task)` and actor is an assignee |
| APPROVE | `approve` | open review exists and `can_decide(...)` |
| REQUEST_CHANGES | `request_changes` | open review exists and `can_decide(...)`; `requires_comment` is always True |
| TIMER, SYSTEM | skipped | |

If MANUAL and another trigger target the same status, keep MANUAL.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_board.py`, using the `world` fixture and `f.make_task`. Helper: `moves(client, task) -> dict[str, str]` returning `{to_status: action}` for that card from the board response.

```python
def test_backlog_card_offers_assign_to_manager_only(world): ...
    # manager: {"ASSIGNED": "assign", "CANCELLED": "transition"}; member: {}
def test_assigned_card_for_member(world): ...
    # member assignee: {"IN_PROGRESS": "transition", "BLOCKED": "transition"}
def test_in_progress_card_submit_only_for_assignee(world): ...
    # member assignee has IN_REVIEW: "submit"; member2 (not assignee) has no IN_REVIEW
def test_submit_allowed_when_creator_is_fallback_reviewer(world): ...
    # task.reviewer is None, created by manager: assignee still gets IN_REVIEW "submit"
def test_in_review_card_offers_decisions_to_reviewer(world): ...
    # reviewer (manager): {"COMPLETED": "approve", "IN_PROGRESS": "request_changes"}, IN_PROGRESS requires_comment True
def test_self_review_blocks_approve_move(world): ...
    # manager is reviewer AND assignee: no COMPLETED, no IN_PROGRESS
def test_completed_task_moves_by_role(world): ...
    # admin/manager: {"REOPENED": "transition"} requires_comment True; member: {}
def test_board_query_count_is_constant(world, django_assert_max_num_queries): ...
    # board with 3 tasks and with 15 tasks uses the same number of queries
```

- [ ] **Step 2: Run, expect FAIL** (KeyError on `allowed_moves`)

Run: `cd backend && uv run pytest tests/test_board.py -v`

- [ ] **Step 3: Implement**
  - `reviews.services.can_decide` from the checks currently inline in `_decide` (lines ~90-99); `_decide` calls it and raises the same errors/codes as today when it returns False (keep the existing distinct `not_reviewer` / `self_review` codes by checking which condition failed).
  - `tasks.board.allowed_moves` per the table above.
  - `TaskBoardView.get`: load the company's active rules once, prefetch `assignees` and pending reviews for the board tasks, pass them in; build cards with `BoardCard(task, context={"request": request, "rules": rules})`.

- [ ] **Step 4: Run, expect PASS**, plus no regressions

Run: `cd backend && uv run pytest tests/test_board.py tests/test_reviews.py tests/test_workflow.py tests/test_tasks.py -v`

- [ ] **Step 5: Regenerate API client and lint**

Run: `make api-client` then `cd backend && uv run ruff check . && uv run ruff format --check .`
Expected: `schema.d.ts` contains `allowed_moves`; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/tasks/board.py backend/apps/reviews/services.py backend/apps/tasks/serializers.py backend/apps/tasks/views.py backend/tests/test_board.py frontend/openapi.json frontend/lib/api/schema.d.ts
git commit -m "feat(tasks): return allowed board moves per card"
```

---

### Task 2: Frontend drop planning (pure logic)

**Files:**
- Create: `frontend/components/tasks/board-moves.ts`
- Test: `frontend/tests/unit/board-moves.test.ts`

**Interfaces:**
- Consumes: `components["schemas"]["BoardCard"]`, `["AllowedMove"]` from Task 1.
- Produces:
  - `export const BOARD_ROWS: TaskStatus[][]` = the two rows from Global Constraints.
  - `export type DropPlan = { kind: "transition"; to: TaskStatus; needsComment: boolean } | { kind: "assign" } | { kind: "submit"; needsReviewer: boolean } | { kind: "approve" } | { kind: "request_changes" }`
  - `export function planDrop(card: BoardCard, to: TaskStatus): DropPlan | null` (null when `to` is the card's status or not in `allowed_moves`).
  - `export function canDrop(card: BoardCard, to: TaskStatus): boolean`

`needsReviewer` is true only when `card.reviewer` is null AND the creator fallback is unavailable; the board card does not carry `created_by`, so set it to `false` and let the submit endpoint's `reviewer_required` error open the reviewer picker (Task 3).

- [ ] **Step 1: Failing tests**

```ts
it("returns null for same column", ...)              // planDrop(card IN_PROGRESS, "IN_PROGRESS") === null
it("returns null for a move not in allowed_moves", ...)
it("maps assign/submit/approve/request_changes", ...)  // each action → its kind
it("transition keeps requires_comment", ...)          // { kind:"transition", to:"BLOCKED", needsComment:true }
it("BOARD_ROWS covers all 9 statuses once", ...)
```

- [ ] **Step 2: Run, expect FAIL.** `cd frontend && npx vitest run tests/unit/board-moves.test.ts`
- [ ] **Step 3: Implement** the three exports.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(board): plan drops from allowed moves`

---

### Task 3: Board UI: layout, dimming, drop actions, cards

**Files:**
- Create: `frontend/components/tasks/board-dialogs.tsx` (assign, reviewer+submit, approve, comment dialogs)
- Modify: `frontend/components/tasks/task-views.tsx` (`BoardCard`, `Column`, `TaskBoard`; `useMoveTask` stays for the task page)
- Modify: `frontend/app/(app)/tasks/page.tsx` (default view `board`)
- Test: `frontend/tests/unit/task-board.test.tsx`

**Interfaces:**
- Consumes: `BOARD_ROWS`, `planDrop`, `canDrop` (Task 2); endpoints `POST /tasks/{id}/transition/` (`{to_status, comment, version}`), `POST /tasks/{id}/assignees/` (`{user_ids}`), `PATCH /tasks/{id}/` (`{reviewer_id, version}`), `POST /tasks/{id}/review/submit/` (`{note}`), `.../review/approve/` (`{comment}`), `.../review/request-changes/` (`{comment}`); `PeoplePicker` from `components/common/people-picker.tsx`; `ConfirmDialog` with `reasonRequired`.
- Produces: `export function TaskBoard({ projectId }: { projectId: string })` (same signature as today).

Behaviour:
- Layout: each row is a CSS grid, row 1 `lg:grid-cols-5`, row 2 `lg:grid-cols-4`, `sm:grid-cols-2`, base 1 column. Remove `overflow-x-auto`, `snap-x`, fixed `w-[82vw] sm:w-72`.
- While dragging (`onDragStart` stores the active card), columns where `!canDrop(card, status)` get `opacity-40` and `useDroppable({ id, disabled: true })`; the source column stays normal.
- On drop: `planDrop` → `transition` without comment, call at once; anything needing input opens the matching dialog; dialog cancel leaves the card in place.
- Optimistic: move the card in the `["get","/api/v1/tasks/board/"]` query cache on confirm; on error restore the previous cache and `toast.error(errorMessage(e))`; always invalidate board and `/api/v1/tasks/` after.
- Submit: if the API returns `reviewer_required`, open the reviewer picker, `PATCH reviewer_id`, then submit again.
- Card: key, priority, 2-line title link, assignee avatars, due date (red when `is_overdue`), reviewer avatar when status is IN_REVIEW, a red "Blocked" chip when BLOCKED, an amber "Needs reassignment" chip when `needs_reassignment`.
- Mobile "Move to…" select lists only `allowed_moves` and runs the same flow.

- [ ] **Step 1: Failing tests** (mock `$api`/`api` like existing unit tests; render `TaskBoard` with a fixture board)

```tsx
it("renders 9 columns in two rows in BOARD_ROWS order", ...)
it("dims columns not in allowed_moves while dragging", ...)       // simulate via keyboard sensor: space, arrow, check opacity class
it("opens assignee dialog when dropping on Assigned", ...)
it("asks for a comment when moving to Blocked", ...)
it("rolls back card when move fails", ...)                        // transition rejects with version_conflict → card back in original column, toast shown
```

- [ ] **Step 2: Run, expect FAIL.** `cd frontend && npx vitest run tests/unit/task-board.test.tsx`
- [ ] **Step 3: Implement** per Behaviour above.
- [ ] **Step 4: Run, expect PASS**, then `npm run lint && npm run typecheck && npm test`.
- [ ] **Step 5: Manual check** with `make up`: as Manager drag a Backlog card to Assigned (assign popup), as the assignee drag In progress → In review, as reviewer drag to Completed; confirm no horizontal scrollbar at 1280px and 1920px.
- [ ] **Step 6: Commit** `feat(board): drag to any column runs the matching workflow action`

---

### Task 4: History line for status moves

**Files:**
- Modify: `frontend/components/tasks/detail-panels.tsx:492-532` (`ActivityPanel`)
- Test: `frontend/tests/unit/activity-panel.test.tsx`

**Interfaces:**
- Consumes: activity rows from `GET /tasks/{id}/activity/`; `status_changed` rows carry `data = {from, to, trigger, comment}` (written by `transition_task`).

Render `status_changed` as: `<actor> moved <StatusBadge from> → <StatusBadge to> · <relative time>`, comment underneath in quotes when present. Other verbs unchanged. Show `formatDateTime` as a `title` tooltip on the relative time.

- [ ] **Step 1: Failing test** `it("shows from and to status for status_changed", ...)`: row `{verb:"status_changed", data:{from:"IN_PROGRESS", to:"IN_REVIEW", comment:"done"}}` renders "In progress", "In review" and "“done”".
- [ ] **Step 2: Run, expect FAIL.** `npx vitest run tests/unit/activity-panel.test.tsx`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS**, then `npm test`.
- [ ] **Step 5: Commit** `feat(tasks): show from/to status in task history`
