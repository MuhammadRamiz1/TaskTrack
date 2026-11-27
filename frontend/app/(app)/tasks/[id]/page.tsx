"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ChevronDown, Flag, Lock, Pencil, RotateCcw, Trash2, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { TaskTimerButton } from "@/components/layout/timer-bar";
import {
  ActivityPanel, AttachmentsPanel, ChecklistsPanel, CommentsPanel, RelationsPanel, ReviewPanel, TimeLogPanel,
} from "@/components/tasks/detail-panels";
import { PriorityBadge, STATUS_META, StatusBadge, type TaskStatus } from "@/components/tasks/meta";
import { TaskFormDialog } from "@/components/tasks/task-form";
import { useMoveTask } from "@/components/tasks/task-views";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter, Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/overlay";
import { Avatar, Badge, Card, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { useMe, useSession } from "@/lib/auth/session";
import { formatDate, formatDuration } from "@/lib/utils";

function TextBlock({ title, text }: { title: string; text?: string | null }) {
  if (!text) return null;
  return (
    <section>
      <h2 className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted">{title}</h2>
      <p className="whitespace-pre-wrap break-words text-[15px] leading-relaxed text-ink">{text}</p>
    </section>
  );
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const { can } = useSession();
  const path = { params: { path: { task_id: id } } };
  const query = $api.useQuery("get", "/api/v1/tasks/{task_id}/", path);
  const [editing, setEditing] = useState(false);
  const [subtask, setSubtask] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "reopen" | "escalate" | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [picked, setPicked] = useState<Person[]>([]);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/{task_id}/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/{task_id}/activity/"] });
  };
  const { move, dialog } = useMoveTask(refresh);
  const remove = $api.useMutation("delete", "/api/v1/tasks/{task_id}/", {
    onSuccess: () => { toast.success("Task deleted. It can be restored for 30 days."); router.replace("/tasks"); },
  });
  const reopen = $api.useMutation("post", "/api/v1/tasks/{task_id}/reopen/", { onSuccess: () => { refresh(); setConfirm(null); } });
  const escalate = $api.useMutation("post", "/api/v1/tasks/{task_id}/escalate/", {
    onSuccess: (r) => { refresh(); setConfirm(null); toast.success(`Escalated to ${r.count} manager(s)`); },
  });
  const assign = $api.useMutation("post", "/api/v1/tasks/{task_id}/assignees/", {
    onSuccess: () => { refresh(); setAssigning(false); setPicked([]); toast.success("Assigned"); },
  });
  const unassign = $api.useMutation("delete", "/api/v1/tasks/{task_id}/assignees/{user_id}/", { onSuccess: refresh });

  if (!query.data) return query.isPending ? <LoadingRows rows={6} /> : <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const task = query.data;
  const isAssignee = task.assignees.some((a) => a.user.id === me.id);
  const manual = task.allowed_transitions.filter((t) => t.to_status !== "REOPENED");
  // Only the creator may delete, and only before work starts (the API enforces the same rule).
  const deletable = can("task.delete") && task.created_by.id === me.id && (task.status === "BACKLOG" || task.status === "ASSIGNED");
  const timerable = isAssignee && ["ASSIGNED", "IN_PROGRESS", "REOPENED"].includes(task.status!);

  return (
    <>
      <Link href="/tasks" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-link">
        <ArrowLeft className="size-4" /> Tasks
      </Link>
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-muted">{task.key}</span>
            <StatusBadge status={task.status!} />
            <PriorityBadge priority={task.priority!} />
            {task.is_read_only && <Badge><Lock className="size-3" /> Read-only</Badge>}
            {task.needs_reassignment && <Badge tone="danger"><Flag className="size-3" /> Needs reassignment</Badge>}
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-ink md:text-[28px]">{task.title}</h1>
          <p className="mt-1 text-sm text-muted">
            {task.project.key} · {task.project.name} · created by {task.created_by.full_name}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {timerable && <TaskTimerButton taskId={task.id} />}
          {manual.length > 0 && (
            <Dropdown>
              <DropdownTrigger asChild>
                <Button variant="outline">Move to <ChevronDown /></Button>
              </DropdownTrigger>
              <DropdownContent>
                {manual.map((t) => (
                  <DropdownItem key={t.to_status} onSelect={() => void move(task, t.to_status as TaskStatus)}>
                    {STATUS_META[t.to_status as TaskStatus].label}{t.requires_comment && <span className="ml-auto text-xs text-muted">needs comment</span>}
                  </DropdownItem>
                ))}
              </DropdownContent>
            </Dropdown>
          )}
          {task.status === "COMPLETED" && can("task.reopen") && (
            <Button variant="outline" onClick={() => setConfirm("reopen")}><RotateCcw /> Reopen</Button>
          )}
          {task.status === "BLOCKED" && can("task.escalate") && (
            <Button variant="outline" onClick={() => setConfirm("escalate")}><AlertTriangle /> Escalate</Button>
          )}
          {can("task.update") && !task.is_read_only && task.status !== "IN_REVIEW" && (
            <Button variant="outline" onClick={() => setEditing(true)}><Pencil /> Edit</Button>
          )}
          {deletable && (
            <Button variant="ghost" size="icon" aria-label="Delete task" onClick={() => setConfirm("delete")}><Trash2 /></Button>
          )}
        </div>
      </div>

      {task.status === "BLOCKED" && task.blocked_reason && (
        <div role="status" className="mb-5 flex gap-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
          <AlertTriangle className="size-5 shrink-0" /> <span><strong>Blocked:</strong> {task.blocked_reason}</span>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card className="flex flex-col gap-5 p-5">
            <TextBlock title="Description" text={task.description} />
            <TextBlock title="Instructions" text={task.instructions} />
            <TextBlock title="Acceptance criteria" text={task.acceptance_criteria} />
            {!task.description && !task.instructions && !task.acceptance_criteria && <p className="text-sm text-muted">No description yet.</p>}
          </Card>
          <ChecklistsPanel task={task} />
          <RelationsPanel task={task} onNewSubtask={() => setSubtask(true)} />
          <CommentsPanel task={task} />
          <AttachmentsPanel task={task} />
          <ActivityPanel taskId={task.id} />
        </div>
        <aside className="flex flex-col gap-5">
          <Card>
            <CardHeader title="Details" />
            <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-3 p-5 text-sm">
              <dt className="text-muted">Assignees</dt>
              <dd className="flex flex-col gap-1.5">
                {task.assignees.length === 0 && <span className="text-muted">Unassigned</span>}
                {task.assignees.map((a) => (
                  <span key={a.user.id} className="flex items-center gap-2">
                    <Avatar name={a.user.full_name} className="size-6" />
                    <span className="min-w-0 flex-1 truncate font-semibold">{a.user.full_name}</span>
                    {a.acknowledged_at && <span className="text-xs text-success" title="Acknowledged">✓</span>}
                    {can("task.assign") && !task.is_read_only && (
                      <button type="button" className="text-muted hover:text-danger" aria-label={`Unassign ${a.user.full_name}`}
                              onClick={() => unassign.mutate({ params: { path: { task_id: task.id, user_id: a.user.id } } })}>
                        <X className="size-4" />
                      </button>
                    )}
                  </span>
                ))}
                {can("task.assign") && !task.is_read_only && (
                  <Button variant="link" size="sm" className="justify-start" onClick={() => setAssigning(true)}><UserPlus /> Assign</Button>
                )}
              </dd>
              <dt className="text-muted">Reviewer</dt><dd className="font-semibold">{task.reviewer?.full_name ?? `${task.created_by.full_name} (creator)`}</dd>
              <dt className="text-muted">Start</dt><dd>{formatDate(task.start_date)}</dd>
              <dt className="text-muted">Due</dt><dd className={task.is_overdue ? "font-semibold text-danger" : ""}>{formatDate(task.due_date)}</dd>
              <dt className="text-muted">Estimate</dt><dd>{task.estimated_minutes ? formatDuration(task.estimated_minutes * 60) : "—"}</dd>
              {task.completed_at && <><dt className="text-muted">Completed</dt><dd>{formatDate(task.completed_at)}</dd></>}
            </dl>
          </Card>
          <ReviewPanel task={task} />
          <TimeLogPanel task={task} />
        </aside>
      </div>

      {dialog}
      {editing && <TaskFormDialog task={task} onClose={() => setEditing(false)} />}
      {subtask && <TaskFormDialog parent={{ id: task.id, key: task.key }} onClose={() => setSubtask(false)} />}
      <Dialog open={assigning} onOpenChange={setAssigning}>
        <DialogContent title={`Assign ${task.key}`} description="People must be in the project or its team.">
          <PeoplePicker label="Assignees" value={picked} onChange={setPicked} exclude={task.assignees.map((a) => a.user.id)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssigning(false)}>Cancel</Button>
            <Button disabled={!picked.length} loading={assign.isPending}
                    onClick={() => assign.mutate({ ...path, body: { user_ids: picked.map((p) => p.id) } })}>Assign</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={confirm === "delete"} onOpenChange={() => setConfirm(null)} title={`Delete ${task.key}?`}
                     description="You can restore it within 30 days." confirmLabel="Delete" danger loading={remove.isPending}
                     onConfirm={() => remove.mutate(path)} />
      <ConfirmDialog open={confirm === "reopen"} onOpenChange={() => setConfirm(null)} title={`Reopen ${task.key}?`}
                     description="The task becomes editable again and the next review starts a new round." reasonLabel="Why reopen?" reasonRequired
                     confirmLabel="Reopen" loading={reopen.isPending} onConfirm={(comment) => reopen.mutate({ ...path, body: { comment } })} />
      <ConfirmDialog open={confirm === "escalate"} onOpenChange={() => setConfirm(null)} title="Escalate to managers"
                     description="Managers responsible for this project are notified." reasonLabel="Note (optional)"
                     confirmLabel="Escalate" loading={escalate.isPending} onConfirm={(note) => escalate.mutate({ ...path, body: { note } })} />
    </>
  );
}
