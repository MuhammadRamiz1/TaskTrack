"use client";

import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { useQueryClient } from "@tanstack/react-query";
import { addDays, endOfMonth, endOfWeek, format, isSameMonth, isToday, startOfMonth, startOfWeek } from "date-fns";
import { CalendarClock, ChevronLeft, ChevronRight, Flag } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ResponsiveTable } from "@/components/common/pager";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/ui/overlay";
import { Avatar, Badge, Card } from "@/components/ui/primitives";
import { EmptyState, QueryState } from "@/components/ui/states";
import { $api, api } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cn, formatDate } from "@/lib/utils";

import { PriorityBadge, STATUS_META, StatusBadge, STATUSES, type TaskStatus } from "./meta";

export type TaskSummary = components["schemas"]["TaskSummary"];

function Assignees({ task, max = 3 }: { task: TaskSummary; max?: number }) {
  if (!task.assignees.length) return <span className="text-sm text-muted">Unassigned</span>;
  return (
    <span className="flex -space-x-2" aria-label={task.assignees.map((a) => a.user.full_name).join(", ")}>
      {task.assignees.slice(0, max).map((a) => (
        <Avatar key={a.user.id} name={a.user.full_name} className="size-7 ring-2 ring-surface" />
      ))}
      {task.assignees.length > max && (
        <span className="grid size-7 place-items-center rounded-full bg-surface-2 text-[11px] font-bold ring-2 ring-surface">
          +{task.assignees.length - max}
        </span>
      )}
    </span>
  );
}

function Due({ task }: { task: TaskSummary }) {
  if (!task.due_date) return <span className="text-muted">—</span>;
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm", task.is_overdue ? "font-semibold text-danger" : "text-ink")}>
      <CalendarClock className="size-3.5" aria-hidden />
      {formatDate(task.due_date, "d MMM")}
      {task.is_overdue && <span className="sr-only">(overdue)</span>}
    </span>
  );
}

export function TaskTable({ tasks }: { tasks: TaskSummary[] }) {
  const router = useRouter();
  return (
    <ResponsiveTable
      caption="Tasks"
      rows={tasks}
      rowKey={(t) => t.id}
      onRowClick={(t) => router.push(`/tasks/${t.id}`)}
      columns={[
        {
          header: "Task",
          cell: (t) => (
            <span className="flex min-w-0 flex-col">
              <span className="font-mono text-xs text-muted">{t.key}</span>
              <span className="truncate font-semibold text-ink">{t.title}</span>
            </span>
          ),
        },
        { header: "Status", cell: (t) => <span className="flex items-center gap-1.5"><StatusBadge status={t.status!} />{t.needs_reassignment && <Badge tone="danger"><Flag className="size-3" /> Reassign</Badge>}</span> },
        { header: "Priority", cell: (t) => <PriorityBadge priority={t.priority!} /> },
        { header: "Assignees", cell: (t) => <Assignees task={t} /> },
        { header: "Due", cell: (t) => <Due task={t} /> },
      ]}
    />
  );
}

/** Moves a task through the transition API; asks for a comment when the rule needs one. */
export function useMoveTask(onSettled?: () => void) {
  const qc = useQueryClient();
  const [pending, setPending] = useState<{ task: TaskSummary; to: TaskStatus } | null>(null);
  const [busy, setBusy] = useState(false);
  const move = async (task: TaskSummary, to: TaskStatus, comment = "") => {
    setBusy(true);
    try {
      await api.POST("/api/v1/tasks/{task_id}/transition/", {
        params: { path: { task_id: task.id } },
        body: { to_status: to, comment, version: task.version },
      });
      toast.success(`${task.key} → ${STATUS_META[to].label}`);
      setPending(null);
    } catch (error) {
      if (error instanceof ApiError && error.code === "comment_required") setPending({ task, to });
      else toast.error(errorMessage(error));
    } finally {
      setBusy(false);
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/board/"] });
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/"] });
      onSettled?.();
    }
  };
  const dialog = (
    <ConfirmDialog
      open={Boolean(pending)}
      onOpenChange={(o) => !o && setPending(null)}
      title={pending ? `Move ${pending.task.key} to ${STATUS_META[pending.to].label}` : ""}
      description="This status change needs a comment."
      reasonLabel={pending?.to === "BLOCKED" ? "What is blocking it?" : "Comment"}
      reasonRequired
      confirmLabel="Move task"
      loading={busy}
      onConfirm={(comment) => pending && void move(pending.task, pending.to, comment)}
    />
  );
  return { move, dialog, busy };
}

function BoardCard({ task, onMove }: { task: TaskSummary; onMove: (to: TaskStatus) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.id, data: task });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <article
      ref={setNodeRef}
      style={style}
      className={cn(
        "rounded-xl border border-line bg-surface p-3 shadow-sm transition-shadow",
        isDragging && "z-10 rotate-1 shadow-card",
      )}
    >
      <div {...listeners} {...attributes} className="cursor-grab touch-none active:cursor-grabbing" aria-roledescription="Draggable task"
           aria-label={`${task.key} ${task.title}. Press space to pick up, arrow keys to move, space to drop.`}>
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-muted">{task.key}</span>
          <PriorityBadge priority={task.priority!} compact />
        </div>
        <Link href={`/tasks/${task.id}`} className="line-clamp-2 text-sm font-semibold text-ink hover:underline"
              onPointerDown={(e) => e.stopPropagation()}>
          {task.title}
        </Link>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <Assignees task={task} max={2} />
        <Due task={task} />
      </div>
      <Select
        aria-label={`Move ${task.key} to`}
        className="mt-2 h-9 text-xs md:hidden"
        value=""
        onChange={(e) => e.target.value && onMove(e.target.value as TaskStatus)}
      >
        <option value="">Move to…</option>
        {STATUSES.filter((s) => s.value !== task.status).map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </Select>
    </article>
  );
}

function Column({ status, tasks, onMove }: { status: TaskStatus; tasks: TaskSummary[]; onMove: (t: TaskSummary, to: TaskStatus) => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <section
      ref={setNodeRef}
      aria-label={`${STATUS_META[status].label}, ${tasks.length} tasks`}
      className={cn(
        "flex w-[82vw] shrink-0 snap-start flex-col rounded-2xl bg-surface-2 p-2.5 transition-colors sm:w-72",
        isOver && "bg-primary-100 ring-2 ring-primary-300",
      )}
    >
      <header className="mb-2 flex items-center justify-between px-1">
        <StatusBadge status={status} />
        <span className="text-xs font-bold text-muted">{tasks.length}</span>
      </header>
      <div className="flex min-h-24 flex-col gap-2">
        {tasks.map((t) => <BoardCard key={t.id} task={t} onMove={(to) => onMove(t, to)} />)}
      </div>
    </section>
  );
}

export function TaskBoard({ projectId }: { projectId: string }) {
  const board = $api.useQuery("get", "/api/v1/tasks/board/", { params: { query: { project: projectId } } });
  const { move, dialog } = useMoveTask();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));
  const onDragEnd = (e: DragEndEvent) => {
    const task = e.active.data.current as TaskSummary | undefined;
    const to = e.over?.id as TaskStatus | undefined;
    if (task && to && to !== task.status) void move(task, to);
  };
  return (
    <QueryState query={board}>
      {(data) => {
        const columns = data.columns;
        const visible = columns.filter((c) => c.status !== "CANCELLED" || c.tasks.length);
        return (
          <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-4 md:mx-0 md:px-0">
              {visible.map((c) => <Column key={c.status} status={c.status} tasks={c.tasks} onMove={(t, to) => void move(t, to)} />)}
            </div>
            {dialog}
          </DndContext>
        );
      }}
    </QueryState>
  );
}

export function TaskCalendar({ month, onMonth }: { month: Date; onMonth: (d: Date) => void }) {
  const gridStart = startOfWeek(startOfMonth(month), { weekStartsOn: 1 });
  const gridEnd = endOfWeek(endOfMonth(month), { weekStartsOn: 1 });
  const tasks = $api.useQuery("get", "/api/v1/tasks/calendar/", {
    params: { query: { start: format(gridStart, "yyyy-MM-dd"), end: format(gridEnd, "yyyy-MM-dd") } },
  });
  const byDay = useMemo(() => {
    const map = new Map<string, TaskSummary[]>();
    for (const t of tasks.data ?? []) if (t.due_date) map.set(t.due_date, [...(map.get(t.due_date) ?? []), t]);
    return map;
  }, [tasks.data]);
  const days: Date[] = [];
  for (let d = gridStart; d <= gridEnd; d = addDays(d, 1)) days.push(d);
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line p-3">
        <Button variant="ghost" size="icon" aria-label="Previous month" onClick={() => onMonth(addDays(startOfMonth(month), -1))}><ChevronLeft /></Button>
        <h2 className="font-bold text-ink">{format(month, "MMMM yyyy")}</h2>
        <Button variant="ghost" size="icon" aria-label="Next month" onClick={() => onMonth(addDays(endOfMonth(month), 1))}><ChevronRight /></Button>
      </div>
      <QueryState query={tasks}>
        {(items) => (
          <>
            {/* Month grid on tablet/desktop */}
            <div className="hidden grid-cols-7 md:grid" role="grid" aria-label="Tasks by due date">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                <div key={d} className="border-b border-line px-2 py-1.5 text-center text-xs font-bold text-muted" role="columnheader">{d}</div>
              ))}
              {days.map((d) => {
                const key = format(d, "yyyy-MM-dd");
                const list = byDay.get(key) ?? [];
                return (
                  <div key={key} role="gridcell" className={cn("min-h-28 border-r border-b border-line p-1.5 [&:nth-child(7n)]:border-r-0",
                    !isSameMonth(d, month) && "bg-surface-2/60")}>
                    <span className={cn("mb-1 inline-grid size-6 place-items-center rounded-full text-xs font-semibold",
                      isToday(d) ? "bg-primary-600 text-on-primary" : "text-muted")}>{format(d, "d")}</span>
                    <ul className="flex flex-col gap-1">
                      {list.slice(0, 3).map((t) => (
                        <li key={t.id}>
                          <Link href={`/tasks/${t.id}`} className={cn("block truncate rounded-md px-1.5 py-0.5 text-xs font-semibold",
                            t.is_overdue ? "bg-danger-soft text-danger" : "bg-primary-100 text-primary-700")}>
                            {t.key} {t.title}
                          </Link>
                        </li>
                      ))}
                      {list.length > 3 && <li className="px-1.5 text-xs text-muted">+{list.length - 3} more</li>}
                    </ul>
                  </div>
                );
              })}
            </div>
            {/* Agenda on phones */}
            <ul className="divide-y divide-line md:hidden">
              {items.length === 0 && <li><EmptyState title="Nothing due this month" /></li>}
              {[...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => (
                <li key={day} className="px-4 py-3">
                  <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted">{formatDate(day, "EEE d MMM")}</p>
                  <ul className="flex flex-col gap-1.5">
                    {list.map((t) => (
                      <li key={t.id}>
                        <Link href={`/tasks/${t.id}`} className="flex items-center justify-between gap-2 rounded-xl bg-surface-2 px-3 py-2">
                          <span className="min-w-0 truncate text-sm font-semibold text-ink">{t.key} {t.title}</span>
                          <StatusBadge status={t.status!} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </QueryState>
    </Card>
  );
}
