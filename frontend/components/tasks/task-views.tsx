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
import { CalendarClock, ChevronLeft, ChevronRight, Clock, Flag, ListChecks, MessageSquare, Paperclip } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
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

import { AssignDialog, ReviewerDialog } from "./board-dialogs";
import { BOARD_ROWS, canDrop, planDrop } from "./board-moves";
import { PriorityBadge, STATUS_META, StatusBadge, type TaskStatus } from "./meta";
import { TaskModal } from "./task-modal";

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

type BoardCardData = components["schemas"]["BoardCard"];
type BoardData = components["schemas"]["BoardOutput"];
const BOARD_KEY = ["get", "/api/v1/tasks/board/"];

type BoardStep =
  | { kind: "transition"; comment: string }
  | { kind: "assign"; userIds: string[] }
  | { kind: "submit"; reviewerId?: string }
  | { kind: "approve"; comment: string }
  | { kind: "request_changes"; comment: string };

type PendingDialog = { card: BoardCardData; to: TaskStatus; dialog: "assign" | "reviewer" | "comment" | "approve" | "changes" };

function moveInCache(data: BoardData, id: string, to: TaskStatus): BoardData {
  const card = data.columns.flatMap((c) => c.tasks).find((t) => t.id === id);
  if (!card) return data;
  return {
    ...data,
    columns: data.columns.map((c) => {
      const rest = c.tasks.filter((t) => t.id !== id);
      return c.status === to ? { ...c, tasks: [{ ...card, status: to }, ...rest] } : { ...c, tasks: rest };
    }),
  };
}

const DOT: Record<string, string> = {
  neutral: "bg-muted", primary: "bg-primary-500", success: "bg-success", warning: "bg-warning", danger: "bg-danger", info: "bg-info",
};

function progressTone(pct: number) {
  if (pct >= 100) return { bar: "bg-success", text: "text-success" };
  if (pct >= 50) return { bar: "bg-warning", text: "text-warning" };
  if (pct > 0) return { bar: "bg-danger", text: "text-danger" };
  return { bar: "bg-line", text: "text-muted" };
}

/** "Sep 17", "Sep 17–Oct 9" or "Oct 15–29" from start and due dates. */
function dateRange(start?: string | null, due?: string | null) {
  const one = due ?? start;
  if (!start || !due || start === due) return one ? formatDate(one, "MMM d") : null;
  const sameMonth = start.slice(0, 7) === due.slice(0, 7);
  return `${formatDate(start, "MMM d")}–${formatDate(due, sameMonth ? "d" : "MMM d")}`;
}

function CardProgress({ task }: { task: BoardCardData }) {
  const { checklist_done: done, checklist_total: total } = task;
  if (!total) return null;
  const pct = Math.round((done / total) * 100);
  const tone = progressTone(pct);
  return (
    <div className="mt-1.5">
      <p className="flex items-center gap-1 text-xs text-muted">
        <ListChecks className="size-3.5" aria-hidden />
        <span>{done}/{total}</span>
        <span aria-hidden>•</span>
        <span className={cn(pct === 100 && "font-semibold", tone.text)}>{pct}% completed</span>
      </p>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct}
           aria-valuemin={0} aria-valuemax={100} aria-label={`${task.key} checklist`}>
        <div className={cn("h-full rounded-full transition-[width]", tone.bar)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function BoardCard({ task, onMove, onOpen }: { task: BoardCardData; onMove: (to: TaskStatus) => void; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: task.id, data: task });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  // A drag ends with a click on the card; this keeps that click from opening the modal.
  const dragged = useRef(false);
  useEffect(() => { if (isDragging) dragged.current = true; }, [isDragging]);
  const range = dateRange(task.start_date, task.due_date);
  return (
    <article
      ref={setNodeRef}
      style={style}
      onPointerDownCapture={() => { dragged.current = false; }}
      onClick={(e) => {
        if (dragged.current || (e.target as HTMLElement).closest("select")) return;
        onOpen();
      }}
      className={cn(
        "cursor-pointer rounded-xl border border-line bg-surface p-3 shadow-sm transition-shadow hover:shadow-card",
        isDragging && "z-10 rotate-1 shadow-card",
      )}
    >
      <div {...listeners} {...attributes} className="cursor-grab touch-none active:cursor-grabbing" aria-roledescription="Draggable task"
           aria-label={`${task.key} ${task.title}. Press space to pick up, arrow keys to move, space to drop.`}>
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            aria-label={`Open ${task.key} details`}
            className="line-clamp-2 text-left text-sm font-semibold text-ink hover:underline"
            onPointerDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); onOpen(); }}
          >
            {task.title}
          </button>
          <PriorityBadge priority={task.priority!} compact />
        </div>
        <CardProgress task={task} />
      </div>
      {(task.status === "BLOCKED" || task.needs_reassignment) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {task.status === "BLOCKED" && <Badge tone="danger">Blocked</Badge>}
          {task.needs_reassignment && <Badge tone="warning">Needs reassignment</Badge>}
        </div>
      )}
      <div className="mt-2.5 flex items-center justify-between gap-2">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted">
          <span className="font-mono">{task.key}</span>
          {task.attachment_count > 0 && (
            <span className="inline-flex items-center gap-0.5" aria-label={`${task.attachment_count} attachment${task.attachment_count === 1 ? "" : "s"}`}>
              <Paperclip className="size-3.5" aria-hidden />{task.attachment_count}
            </span>
          )}
          {task.comment_count > 0 && (
            <span className="inline-flex items-center gap-0.5" aria-label={`${task.comment_count} comment${task.comment_count === 1 ? "" : "s"}`}>
              <MessageSquare className="size-3.5" aria-hidden />{task.comment_count}
            </span>
          )}
          {range && (
            <span className={cn("inline-flex items-center gap-1", task.is_overdue && "font-semibold text-danger")}>
              <Clock className="size-3.5" aria-hidden />{range}
              {task.is_overdue && <span className="sr-only">(overdue)</span>}
            </span>
          )}
        </span>
        <span className="flex flex-none items-center gap-1.5">
          {task.status === "IN_REVIEW" && task.reviewer && (
            <span aria-label={`Reviewer: ${task.reviewer.full_name}`} title={`Reviewer: ${task.reviewer.full_name}`}>
              <Avatar name={task.reviewer.full_name} className="size-6 opacity-80 ring-2 ring-surface" />
            </span>
          )}
          {task.assignees.length > 0 && <Assignees task={task} max={2} />}
        </span>
      </div>
      <Select
        aria-label={`Move ${task.key} to`}
        className="mt-2 h-9 text-xs md:hidden"
        value=""
        onChange={(e) => e.target.value && onMove(e.target.value as TaskStatus)}
      >
        <option value="">Move to…</option>
        {task.allowed_moves.map((m) => <option key={m.to_status} value={m.to_status}>{STATUS_META[m.to_status].label}</option>)}
      </Select>
    </article>
  );
}

function Column({ status, tasks, dimmed, onMove, onOpen }: {
  status: TaskStatus; tasks: BoardCardData[]; dimmed: boolean;
  onMove: (t: BoardCardData, to: TaskStatus) => void; onOpen: (t: BoardCardData) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: status, disabled: dimmed });
  const meta = STATUS_META[status];
  return (
    <section
      ref={setNodeRef}
      aria-label={`${meta.label}, ${tasks.length} tasks`}
      className={cn(
        "flex min-w-0 flex-col self-start rounded-2xl border border-line/60 bg-surface-2/80 p-2.5 shadow-sm transition-[background-color,opacity]",
        dimmed && "opacity-40",
        isOver && "bg-primary-100 ring-2 ring-primary-300",
      )}
    >
      <header className="mb-2.5 flex items-center justify-between gap-2 px-1.5 pt-0.5">
        <h3 className={cn("flex items-center gap-2 text-sm font-bold text-ink", status === "CANCELLED" && "line-through")}>
          <span className={cn("size-2.5 rounded-full ring-2 ring-surface", DOT[meta.tone])} aria-hidden />
          {meta.label}
        </h3>
        <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-bold text-muted">{tasks.length}</span>
      </header>
      <div className="flex min-h-24 flex-col gap-2.5">
        {tasks.map((t) => <BoardCard key={t.id} task={t} onMove={(to) => onMove(t, to)} onOpen={() => onOpen(t)} />)}
        {tasks.length === 0 && <p className="grid min-h-20 place-items-center rounded-xl border border-dashed border-line text-xs text-muted">No tasks</p>}
      </div>
    </section>
  );
}

export function TaskBoard({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const board = $api.useQuery("get", "/api/v1/tasks/board/", { params: { query: { project: projectId } } });
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor));
  const [active, setActive] = useState<BoardCardData | null>(null);
  const [pending, setPending] = useState<PendingDialog | null>(null);
  const [opened, setOpened] = useState<BoardCardData | null>(null);

  const call = async (card: BoardCardData, to: TaskStatus, step: BoardStep) => {
    const path = { params: { path: { task_id: card.id } } };
    switch (step.kind) {
      case "transition":
        return api.POST("/api/v1/tasks/{task_id}/transition/", { ...path, body: { to_status: to, comment: step.comment, version: card.version } });
      case "assign":
        return api.POST("/api/v1/tasks/{task_id}/assignees/", { ...path, body: { user_ids: step.userIds } });
      case "submit":
        if (step.reviewerId) await api.PATCH("/api/v1/tasks/{task_id}/", { ...path, body: { reviewer_id: step.reviewerId, version: card.version } });
        return api.POST("/api/v1/tasks/{task_id}/review/submit/", { ...path, body: { note: "" } });
      case "approve":
        return api.POST("/api/v1/tasks/{task_id}/review/approve/", { ...path, body: { comment: step.comment } });
      case "request_changes":
        return api.POST("/api/v1/tasks/{task_id}/review/request-changes/", { ...path, body: { comment: step.comment } });
    }
  };

  /** Moves the card in the cache at once, then rolls back and reports if the server refuses. */
  const execute = async (card: BoardCardData, to: TaskStatus, step: BoardStep) => {
    setPending(null);
    await qc.cancelQueries({ queryKey: BOARD_KEY });
    const snapshot = qc.getQueriesData<BoardData>({ queryKey: BOARD_KEY });
    qc.setQueriesData<BoardData>({ queryKey: BOARD_KEY }, (d) => (d ? moveInCache(d, card.id, to) : d));
    try {
      await call(card, to, step);
      toast.success(`${card.key} → ${STATUS_META[to].label}`);
    } catch (error) {
      for (const [key, data] of snapshot) qc.setQueryData(key, data);
      if (error instanceof ApiError && error.code === "reviewer_required" && step.kind === "submit") setPending({ card, to, dialog: "reviewer" });
      else if (error instanceof ApiError && error.code === "comment_required" && step.kind === "transition") setPending({ card, to, dialog: "comment" });
      else toast.error(errorMessage(error));
    } finally {
      void qc.invalidateQueries({ queryKey: BOARD_KEY });
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/"] });
    }
  };

  const start = (card: BoardCardData, to: TaskStatus) => {
    const plan = planDrop(card, to);
    if (!plan) return;
    switch (plan.kind) {
      case "transition":
        if (plan.needsComment) setPending({ card, to, dialog: "comment" });
        else void execute(card, to, { kind: "transition", comment: "" });
        break;
      case "assign": setPending({ card, to, dialog: "assign" }); break;
      case "submit": void execute(card, to, { kind: "submit" }); break;
      case "approve": setPending({ card, to, dialog: "approve" }); break;
      case "request_changes": setPending({ card, to, dialog: "changes" }); break;
    }
  };

  const onDragEnd = (e: DragEndEvent) => {
    const card = e.active.data.current as BoardCardData | undefined;
    const to = e.over?.id as TaskStatus | undefined;
    setActive(null);
    if (card && to) start(card, to);
  };

  const cancel = () => setPending(null);
  const p = pending;
  return (
    <QueryState query={board}>
      {(data) => (
        <DndContext
          sensors={sensors}
          onDragStart={(e) => setActive((e.active.data.current as BoardCardData | undefined) ?? null)}
          onDragEnd={onDragEnd}
          onDragCancel={() => setActive(null)}
        >
          <div className="flex flex-col gap-3 pb-4">
            {BOARD_ROWS.map((row, i) => (
              <div key={i} data-testid="board-row"
                   className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2", i === 0 ? "lg:grid-cols-5" : "lg:grid-cols-4")}>
                {row.map((status) => (
                  <Column
                    key={status}
                    status={status}
                    tasks={data.columns.find((c) => c.status === status)?.tasks ?? []}
                    dimmed={Boolean(active) && active!.status !== status && !canDrop(active!, status)}
                    onMove={start}
                    onOpen={setOpened}
                  />
                ))}
              </div>
            ))}
          </div>
          <TaskModal
            taskId={opened?.id ?? null}
            title={opened?.title ?? ""}
            onClose={() => {
              setOpened(null);
              void qc.invalidateQueries({ queryKey: BOARD_KEY }); // checklist, comment and file counts may have changed
            }}
          />
          <AssignDialog taskKey={p?.card.key ?? ""} open={p?.dialog === "assign"} onCancel={cancel}
                        onConfirm={(userIds) => p && void execute(p.card, p.to, { kind: "assign", userIds })} />
          <ReviewerDialog taskKey={p?.card.key ?? ""} open={p?.dialog === "reviewer"} onCancel={cancel}
                          onConfirm={(reviewerId) => p && void execute(p.card, p.to, { kind: "submit", reviewerId })} />
          <ConfirmDialog
            open={p?.dialog === "comment"}
            onOpenChange={(o) => !o && cancel()}
            title={p ? `Move ${p.card.key} to ${STATUS_META[p.to].label}` : ""}
            description="This status change needs a comment."
            reasonLabel={p?.to === "BLOCKED" ? "What is blocking it?" : "Comment"}
            reasonRequired
            confirmLabel="Move task"
            onConfirm={(comment) => p && void execute(p.card, p.to, { kind: "transition", comment })}
          />
          <ConfirmDialog
            open={p?.dialog === "approve"}
            onOpenChange={(o) => !o && cancel()}
            title={p ? `Approve ${p.card.key}?` : ""}
            description="The task becomes COMPLETED and read-only."
            reasonLabel="Comment (optional)"
            confirmLabel="Approve"
            onConfirm={(comment) => p && void execute(p.card, p.to, { kind: "approve", comment })}
          />
          <ConfirmDialog
            open={p?.dialog === "changes"}
            onOpenChange={(o) => !o && cancel()}
            title="Request changes"
            description="The task goes back to IN_PROGRESS."
            reasonLabel="What needs to change?"
            reasonRequired
            confirmLabel="Request changes"
            danger
            onConfirm={(comment) => p && void execute(p.card, p.to, { kind: "request_changes", comment })}
          />
        </DndContext>
      )}
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
