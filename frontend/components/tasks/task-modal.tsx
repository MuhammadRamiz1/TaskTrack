"use client";

import { AlertTriangle, ExternalLink, Flag, Lock } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/overlay";
import { Avatar, Badge } from "@/components/ui/primitives";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { formatDate, formatDuration } from "@/lib/utils";

import { AttachmentsPanel, ChecklistsPanel, CommentsPanel, type TaskDetail } from "./detail-panels";
import { PriorityBadge, StatusBadge } from "./meta";

function TextBlock({ title, text }: { title: string; text?: string | null }) {
  if (!text) return null;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted">{title}</h3>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{text}</p>
    </section>
  );
}

function Person({ name }: { name: string }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Avatar name={name} className="size-6" />
      <span className="truncate font-semibold">{name}</span>
    </span>
  );
}

function Refs({ title, items }: { title: string; items: { id: string; key: string; title: string; status?: TaskDetail["status"] }[] }) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted">{title}</h3>
      <ul className="flex flex-col gap-1.5">
        {items.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
            <Link href={`/tasks/${r.id}`} className="min-w-0 truncate font-semibold text-ink hover:underline">
              <span className="font-mono text-xs text-muted">{r.key}</span> {r.title}
            </Link>
            {r.status && <StatusBadge status={r.status} />}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Body({ task }: { task: TaskDetail }) {
  const deps = task.dependencies.map((d) => d.blocked_by);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-muted">{task.key}</span>
        <StatusBadge status={task.status!} />
        <PriorityBadge priority={task.priority!} />
        {task.is_read_only && <Badge><Lock className="size-3" /> Read-only</Badge>}
        {task.needs_reassignment && <Badge tone="danger"><Flag className="size-3" /> Needs reassignment</Badge>}
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <Link href={`/tasks/${task.id}`}><ExternalLink /> Open full page</Link>
        </Button>
      </div>

      {task.status === "BLOCKED" && task.blocked_reason && (
        <div role="status" className="flex gap-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
          <AlertTriangle className="size-5 shrink-0" /> <span><strong>Blocked:</strong> {task.blocked_reason}</span>
        </div>
      )}

      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2.5 rounded-2xl bg-surface-2 p-4 text-sm sm:grid-cols-[110px_1fr_110px_1fr]">
        <dt className="text-muted">Project</dt>
        <dd className="truncate font-semibold">{task.project.key} · {task.project.name}</dd>
        <dt className="text-muted">Created by</dt>
        <dd><Person name={task.created_by.full_name} /></dd>
        <dt className="text-muted">Assignees</dt>
        <dd className="flex flex-col gap-1.5">
          {task.assignees.length ? task.assignees.map((a) => <Person key={a.user.id} name={a.user.full_name} />) : <span className="text-muted">Unassigned</span>}
        </dd>
        <dt className="text-muted">Reviewer</dt>
        <dd>{task.reviewer ? <Person name={task.reviewer.full_name} /> : <span className="text-muted">{task.created_by.full_name} (creator)</span>}</dd>
        <dt className="text-muted">Start</dt>
        <dd>{formatDate(task.start_date)}</dd>
        <dt className="text-muted">Due</dt>
        <dd className={task.is_overdue ? "font-semibold text-danger" : ""}>{formatDate(task.due_date)}{task.is_overdue && " (overdue)"}</dd>
        <dt className="text-muted">Estimate</dt>
        <dd>{task.estimated_minutes ? formatDuration(task.estimated_minutes * 60) : "—"}</dd>
        <dt className="text-muted">{task.completed_at ? "Completed" : "Updated"}</dt>
        <dd>{formatDate(task.completed_at ?? task.updated_at)}</dd>
      </dl>

      <TextBlock title="Description" text={task.description} />
      <TextBlock title="Instructions" text={task.instructions} />
      <TextBlock title="Acceptance criteria" text={task.acceptance_criteria} />
      {!task.description && !task.instructions && !task.acceptance_criteria && <p className="text-sm text-muted">No description yet.</p>}

      <Refs title="Subtasks" items={task.subtasks} />
      <Refs title="Blocked by" items={deps} />
      <Refs title="Blocks" items={task.dependents} />

      <ChecklistsPanel task={task} />
      <CommentsPanel task={task} />
      <AttachmentsPanel task={task} />
    </div>
  );
}

/** Full task details in a dialog, opened from a board card. */
export function TaskModal({ taskId, title, onClose }: { taskId: string | null; title: string; onClose: () => void }) {
  const query = $api.useQuery("get", "/api/v1/tasks/{task_id}/", { params: { path: { task_id: taskId ?? "" } } }, { enabled: Boolean(taskId) });
  return (
    <Dialog open={Boolean(taskId)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={query.data?.title ?? title} wide className="md:max-w-3xl">
        {query.data ? <Body task={query.data} /> : query.isPending ? <LoadingRows rows={5} /> : <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      </DialogContent>
    </Dialog>
  );
}
