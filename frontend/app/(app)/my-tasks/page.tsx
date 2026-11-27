"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Flag } from "lucide-react";
import Link from "next/link";

import { TaskTimerButton } from "@/components/layout/timer-bar";
import { PriorityBadge, STATUS_META, StatusBadge, type TaskStatus } from "@/components/tasks/meta";
import type { TaskSummary } from "@/components/tasks/task-views";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { useMe } from "@/lib/auth/session";
import { cn, formatDate } from "@/lib/utils";

const GROUPS: { title: string; statuses: TaskStatus[] }[] = [
  { title: "In progress", statuses: ["IN_PROGRESS", "REOPENED"] },
  { title: "To do", statuses: ["ASSIGNED"] },
  { title: "Waiting", statuses: ["IN_REVIEW", "BLOCKED", "ON_HOLD"] },
];

function MyTaskRow({ task }: { task: TaskSummary }) {
  const me = useMe();
  const qc = useQueryClient();
  const mine = task.assignees.find((a) => a.user.id === me.id);
  const ack = $api.useMutation("post", "/api/v1/tasks/{task_id}/acknowledge/", {
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/"] }),
  });
  const canTime = task.status === "IN_PROGRESS" || task.status === "ASSIGNED" || task.status === "REOPENED";
  return (
    <li className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted">{task.key}</span>
          <StatusBadge status={task.status!} />
          <PriorityBadge priority={task.priority!} />
          {task.needs_reassignment && <Badge tone="danger"><Flag className="size-3" /> Reassignment</Badge>}
        </div>
        <Link href={`/tasks/${task.id}`} className="mt-0.5 block truncate font-semibold text-ink hover:underline">{task.title}</Link>
        <p className={cn("text-xs", task.is_overdue ? "font-semibold text-danger" : "text-muted")}>
          {task.due_date ? `Due ${formatDate(task.due_date)}${task.is_overdue ? " · overdue" : ""}` : "No due date"}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {mine && !mine.acknowledged_at && (
          <Button size="sm" variant="secondary" loading={ack.isPending}
                  onClick={() => ack.mutate({ params: { path: { task_id: task.id } } })}>
            <CheckCheck /> Acknowledge
          </Button>
        )}
        {canTime && <TaskTimerButton taskId={task.id} size="sm" />}
      </div>
    </li>
  );
}

export default function MyTasksPage() {
  const tasks = $api.useQuery("get", "/api/v1/tasks/", {
    params: { query: { mine: true, open: true, page_size: 100, ordering: "-priority_rank" } },
  });
  return (
    <>
      <PageHeader title="My tasks" description="Work assigned to you, most urgent first." />
      <QueryState query={tasks} isEmpty={(d) => !d.results.length}
                  empty={<Card><EmptyState title="Nothing assigned to you" description="New assignments show up here and in your notifications." /></Card>}>
        {(data) => (
          <div className="flex flex-col gap-5">
            {GROUPS.map((g) => {
              const items = data.results.filter((t) => g.statuses.includes(t.status!));
              if (!items.length) return null;
              return (
                <Card key={g.title}>
                  <h2 className="flex items-center gap-2 border-b border-line px-4 py-3 font-bold text-ink">
                    {g.title} <span className="text-sm font-semibold text-muted">{items.length}</span>
                  </h2>
                  <ul className="divide-y divide-line">{items.map((t) => <MyTaskRow key={t.id} task={t} />)}</ul>
                </Card>
              );
            })}
            <p className="text-sm text-muted">
              Showing open work only. {Object.values(STATUS_META).length > 0 && <Link href="/tasks?view=list" className="font-semibold text-link">See all tasks</Link>}
            </p>
          </div>
        )}
      </QueryState>
    </>
  );
}
