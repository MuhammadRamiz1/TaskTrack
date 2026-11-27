# Hours audit report: design

Date: 2026-11-23. Status: awaiting approval.

## Intent

Managers, HR, admins and team leads must be able to audit **which employee worked how
many hours, on which task, on which day**, and see it graphically on the Reports page.
Each viewer sees only the people the organization hierarchy puts under them.

Today the Reports page only sums hours per member/project/team per period
(`apps/reports/selectors.py::time_report`). It never shows the task or the individual
entries, and visibility follows RBAC team/project membership, not the reporting line.
HR has no `time.view` / `report.view` grant, so HR sees nothing.

## Goals

1. A hierarchy-based visibility rule for time entries (below), used by all time
   reporting on the Reports page.
2. An audit view: Employee > Task > Day > individual entries (start, end, duration, note),
   with each employee's team lead(s) and manager shown.
3. Charts: hours per employee split by task, and an employee × day heatmap.
4. Filters: date range, team, employee, project. Export continues to work.

## Non-goals

- Changing visibility on other screens (Timesheets, Approvals, Tasks). They keep RBAC.
- Changing the RBAC engine or adding a new RBAC scope (approach B, rejected for now).
- Editing time entries from the report.
- The task report (`/reports/tasks/`) stays on RBAC `task.view`.

## Anti-goals (failure even if it "works")

- Any viewer seeing hours of someone outside their rule, including across companies.
- A manager seeing their report's hours on unrelated tasks because of a task-level link
  (task-level access is per task only, see rule 4).
- Visibility computed in the frontend.

## Visibility rule (decided with the user)

A viewer V can see a time entry E (employee U, task T) when any of these holds:

1. **Own:** U = V.
2. **Company-wide:** V has the HR or COMPANY_ADMIN role (or SUPER_ADMIN in platform
   context). Sees every entry in the company.
3. **Manager chain:** U is anywhere below V in the `User.manager` chain (direct and
   indirect reports).
4. **Task-level:** V is `T.reviewer`, or V is `assigned_by` on U's `TaskAssignee` row for
   T. Grants E only for that task T.
5. **Team lead:** V is `Team.lead` of a non-archived team that U is a member of
   (`TeamMember`). Grants all of U's entries.

Everyone else sees nothing. A TEAM_MEMBER sees only their own hours (rule 1).

The rule replaces RBAC `time.view` scoping **for the Reports page time data only**
(`time_report`, the time part of `manager_summary`, exports and scheduled exports of
type `time`, and the new audit endpoint). Postgres RLS still enforces tenant isolation
underneath.

## Approaches

- **A. Dedicated visibility function in the reports layer (chosen by the user).**
  One function builds the visible-entries queryset; reports use it. Small, testable.
  Trade-off: other screens still use RBAC, so visibility can differ between Reports and
  Timesheets.
- **B. New RBAC scope** so every `time.view` check follows the hierarchy. Consistent
  everywhere, but touches the policy engine, grants and role editor. Rejected as too
  large and risky for now; A can be promoted to B later.
- **C. A + stored closure table of the manager chain.** Faster for very large orgs but
  needs sync on every manager change. Overkill at current size.

## Design

### Backend

**`apps/reports/visibility.py` (new)**
- `visible_time_entries(actor) -> QuerySet[TimeEntry]`: finished entries
  (`ended_at` not null) matching the rule above, built as one `Q` with `OR`s:
  - `Q(user=actor)`
  - company-wide roles: no extra filter (all tenant rows)
  - `Q(user_id__in=subordinate_ids(actor))`
  - `Q(task__reviewer=actor)`
  - `Q(task__assignees__assigned_by=actor, task__assignees__user=F("user"))`
    (the assignee row must belong to the same employee; must be one `filter()` call so
    both conditions hit the same join)
  - `Q(user__team_memberships__team__lead=actor, user__team_memberships__team__is_archived=False)`
  - `.distinct()` (or `pk__in` subquery) because of the joins.
- `subordinate_ids(actor) -> set[UUID]`: recursive CTE over `accounts_user.manager_id`
  starting at the actor, excluding the actor, with a cycle guard (`UNION`, not
  `UNION ALL`, and a depth cap of 20). Runs inside the request's tenant context, so RLS
  limits it to the company. Cached on the actor for the request (like
  `apps/org/scopes.py::_cache`).
- How "company-wide role" is detected: reuse the rbac helpers for the actor's role keys
  (the builder picks the existing helper; do not hardcode role names in more than one
  place).

**`apps/reports/selectors.py`**
- `scoped_entries` switches from `policy.scope_queryset(actor, "time.view", ...)` to
  `visibility.visible_time_entries(actor)`. Filters (date range, project, team, user)
  are unchanged. This automatically covers `time_report`, `manager_summary`'s time
  figures, and exports.
- New `audit_rows(actor, f)`: entries visible to the actor in range, with
  `select_related` for user, task, project; ordered by employee name, task key,
  `work_date`, `started_at`. Each row: employee id/name, task id/key/title, project key,
  work_date, started_at, ended_at, hours, note, status.
- New `audit_people(actor, f)`: for each employee in the result, their `manager` name and
  the leads of their non-archived teams. One query each, no N+1.
- New `day_matrix(actor, f)`: hours per (employee, work_date), for the heatmap.
- New `task_split(actor, f)`: hours per (employee, task), for the stacked bars. Tasks
  beyond the top 8 per employee by hours are folded into "Other".

**`apps/reports/api.py`**
- `GET /api/v1/reports/time/audit/` with the same `ReportQuery` params. Returns
  `{ totals, people, task_split, day_matrix, entries }`. `entries` is paginated
  (page size 200). Range capped at 92 days (400 otherwise) to bound the payload.
- Permission: `report.view` (any scope). Data scoping comes from the visibility rule,
  not the RBAC scope.
- OpenAPI schema via `extend_schema`. Regenerate the frontend client (`make schema`).

**RBAC catalogue (`apps/rbac/catalogue.py`)**
- HR gets `report.view: C` and `report.export: C`, so HR can open Reports and export.
  HR does **not** get `time.view` / `task.view`, so its access on other screens doesn't
  change.
- New migration in `apps/rbac/migrations` that runs `sync_catalogue` (follow the pattern
  in `0003_seed_catalogue.py` / `0004`), so existing companies get the new grants.

### Frontend (`frontend/app/(app)/reports/page.tsx`)

When the report type is "time", the view becomes:

```
[Date range] [Team] [Employee] [Project]                 [Export]
┌ Total hours ┐┌ Employees ┐┌ Tasks worked ┐┌ Avg hours/day ┐
┌ Hours per employee, stacked by task (horizontal bars) ───────┐
┌ Day heatmap: rows = employees, columns = dates, colour = hrs ┐
┌ Audit table ─────────────────────────────────────────────────┐
│ ▸ emp1 mobi   9.3h   Lead: Ali   Manager: Sara                │
│     ▸ TT-12 Login page        6.0h                            │
│         Mon 17 Nov  09:00–12:00  3.0h  "API wiring"           │
```

- Uses `recharts` (already installed) and the existing `BarChartCard` style. Charts
  follow the `dataviz` skill (palette, accessible colours, light/dark).
- The audit table groups client-side from `entries`. Employee and task rows collapse.
- Times are shown in the viewer's time zone; `work_date` is shown as is.
- The employee filter lists only people the viewer can see (taken from `people`).
- Empty state: "No hours logged by people you can see in this range."

### Tests (`backend/tests/test_reports.py` and a new `test_reports_visibility.py`)

One test per rule, plus negatives:
- Own only for a team member; peer on the same project sees nothing.
- Manager sees direct and indirect reports; doesn't see their own manager or siblings.
- Reviewer / `assigned_by` sees the employee's entries on that task only, not on others.
- `assigned_by` on employee X's assignment doesn't expose employee Y's entries on the
  same task.
- Lead of team sees members' entries; archived team grants nothing.
- HR and company admin see the whole company; nothing from another company (RLS).
- Manager cycle (A→B→A) doesn't loop.
- Audit endpoint returns task, day and entry detail, and the people block.
- Existing report and export tests still pass with the new scoping.

## Decided by the builder / my calls (flag if wrong)

- Draft (not yet submitted) entries are included; the `status` column shows it.
- Running timers (no `ended_at`) are excluded, as today.
- 92-day range cap and 200-row pages for the audit endpoint.
- "Other" bucket beyond the top 8 tasks per employee in the stacked chart.
- Daily, weekly and monthly grouping for the existing time report stays as is.
