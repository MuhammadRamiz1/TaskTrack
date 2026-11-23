# TaskTrack Architecture (Phase 1)

TaskTrack is a multi-tenant SaaS for task assignment, task review and time tracking.
This folder is the design baseline. Later phases implement it. Changes to the design
are made here first, then in code.

| Document | Contents |
| --- | --- |
| [01-system-overview.md](01-system-overview.md) | Context, module diagram, layering, request lifecycle, tenancy and RLS design, auth and session design |
| [02-data-model.md](02-data-model.md) | ERD (Mermaid), table-by-table field list, constraints, indexes, RLS policies |
| [03-rbac.md](03-rbac.md) | Permission catalogue, role-permission-scope matrix, policy layer API, scope resolution rules |
| [04-task-lifecycle.md](04-task-lifecycle.md) | Task state machine, default transition table, review workflow, timer rules, timesheet workflow |
| [05-api.md](05-api.md) | REST endpoint list (`/api/v1/`), error format, pagination, filtering, concurrency, file upload flow |
| [06-project-structure.md](06-project-structure.md) | Backend and frontend folder layout, Docker Compose services, environment variables, CI pipeline, testing strategy |
| [07-frontend-design.md](07-frontend-design.md) | Light-purple theme tokens (light and dark), responsive layout rules, route map, frontend architecture |

## Assumptions

These fill gaps in the brief. Each one is easy to change before Phase 2 starts.

1. **Company Admin role.** The brief mentions "Admin" (HR cannot reset Admin passwords, HR/Admin adjust transitions) but does not list it. The design adds `COMPANY_ADMIN`: full control of one company's settings, roles, workflow and users. It is a seeded system role like the others.
2. **One account per email, platform-wide.** Login is by email only (no company slug). An email belongs to at most one company. Super admins have `company_id = NULL`.
3. **Impersonation is read-only.** A super admin impersonating a company user gets a 30-minute token that allows `GET` only. Every impersonated request is audit-logged with both identities. A write-capable mode can be added later as a separate permission.
4. **Projects belong to exactly one team** (hierarchy Company > Team > Project > Task). Project members can come from any team in the same company.
5. **REOPENED is a real status.** `COMPLETED -> REOPENED` records the reason. Work resumes with `REOPENED -> IN_PROGRESS` (manual, or automatically when a timer starts).
6. **Pause = stop the current time segment.** A paused timer is a closed `TimeEntry`; resume opens a new one. Server stores start timestamps, so timers survive refresh and device changes.
7. **Timesheets are weekly** (company setting `week_start`, default Monday), one per user per week.
8. **Notifications are polled** (TanStack Query, 30 s interval plus refetch on focus). No WebSocket server is added to the fixed stack.
9. **PDF export uses ReportLab** (pure Python, no system libraries). XLSX uses openpyxl.
10. **Same-origin API in the browser.** Next.js rewrites `/api/*` to the Django service, so the refresh cookie is first-party, `SameSite=Strict` works, and production needs no CORS. CORS is still configured for local direct access.
11. **API client: openapi-typescript + openapi-fetch + openapi-react-query** (changed from Orval in Phase 6). Types are generated from the drf-spectacular schema snapshot `frontend/openapi.json`; `$api.useQuery` / `$api.useMutation` give typed TanStack Query hooks without a generated hook layer. CI fails when the snapshot or the generated types drift.
12. **Postgres 16** as specified (the current compose file uses 17; it is changed to 16).
13. **Mail in development: MailHog** as specified. MailHog is unmaintained; Mailpit is a drop-in replacement if the image becomes a problem.
14. **S3 is off by default (`USE_S3=false`).** Attachments and report exports are stored on a local `media` volume and served only through permission-checked API endpoints. Setting `USE_S3=true` stores them in a private S3 bucket instead, through the same endpoints and with no other code changes. MinIO no longer publishes public container images, so the optional local S3 store is SeaweedFS (`docker compose --profile s3 up`). Production can use AWS S3, MinIO, R2 or any S3-compatible service.
15. **Session hint cookie.** The refresh cookie is scoped to `/api/v1/auth/`, so the Next.js proxy cannot see it on page requests. The API also sets a non-secret `tt_session=1` cookie on `/`, which only tells the proxy whether to redirect to `/login`. It grants nothing; every API call still needs the access token.
16. **Comments are plain text with mentions.** Comment bodies are rendered as text (React escapes them), with `@[Name](user:<uuid>)` tokens shown as mention chips. No Markdown or HTML is interpreted, so no sanitiser is needed.
17. **`cacheComponents` is off.** Every app screen is per-user and client-fetched; Next.js component caching adds no value and complicates auth redirects.
18. **Existing code is replaced.** The current `apps/` (single-tenant `Organization`, hardcoded `Role` enum, DRF `TokenAuthentication`) and `apps_old/` are removed in Phase 2. No production data exists, so migrations restart from `0001`. The volume must be reset once (`docker compose down -v`).

## Key decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Primary keys | UUIDv4 | Not guessable, safe in URLs, no cross-tenant enumeration |
| Tenant isolation | `company_id` on every tenant table + `TenantManager` (primary) + Postgres RLS (secondary) | Two independent layers; a missed filter in Python is still blocked by the database |
| RLS context | `SET LOCAL app.company_id` per transaction (`ATOMIC_REQUESTS=True`) | Transaction-scoped, safe with pooled connections |
| DB roles | `tasktrack_owner` (owns tables, runs migrations) and `tasktrack_app` (runtime, `NOBYPASSRLS`, not owner) | Table owners and superusers bypass RLS; the runtime role must be neither |
| Auth tokens | SimpleJWT. Access token 10 min, in memory. Refresh token 14 days, rotating, httpOnly `Secure` `SameSite=Strict` cookie scoped to `/api/v1/auth/` | XSS cannot read the refresh token; CSRF cannot use it cross-site |
| Session revocation | `UserSession` row per refresh-token family + `session_version` claim on access tokens | "Log out everywhere" and password resets invalidate access tokens within one request, not after 10 min |
| Permissions | Data-driven `Role -> RolePermission(scope)` + `UserRole` bindings, evaluated by one policy module | No role names in view code; companies can adjust grants |
| Workflow | `StatusTransitionRule` table per company; single `transition_task()` service | Configurable, auditable, no direct status writes |
| Concurrency | `select_for_update` on transitions and timers; `version` column on Task for optimistic edits; partial unique index for one running timer per user | Correct under parallel requests and multiple devices |
| Files | Django default storage, backend chosen by `USE_S3` (local volume or private S3 bucket). Upload and download always go through the API: type/size/content checks, quota, then a permission-checked stream. Tenant-prefixed keys | Works with no extra infrastructure today; S3 needs only a flag later |
| Background work | Celery + Redis; Beat with a static schedule that dispatches due `ScheduledReport` rows | Emails, reminders, reports, cleanup |
| Audit | Append-only `AuditLog` written in the same transaction as the change; DB trigger blocks `UPDATE`/`DELETE`; runtime role has `INSERT, SELECT` only | Cannot be altered by application bugs |
