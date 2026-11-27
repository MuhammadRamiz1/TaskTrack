import { AlertOctagon, ArrowDown, ArrowUp, ChevronsUp, Minus } from "lucide-react";

import { Badge, type Tone } from "@/components/ui/primitives";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

export type S = components["schemas"];
export type TaskStatus = S["TaskStatusEnum"];
export type TaskPriority = S["PriorityEnum"];

export const STATUSES: { value: TaskStatus; label: string; tone: Tone }[] = [
  { value: "BACKLOG", label: "Backlog", tone: "neutral" },
  { value: "ASSIGNED", label: "Assigned", tone: "primary" },
  { value: "IN_PROGRESS", label: "In progress", tone: "info" },
  { value: "IN_REVIEW", label: "In review", tone: "warning" },
  { value: "ON_HOLD", label: "On hold", tone: "neutral" },
  { value: "BLOCKED", label: "Blocked", tone: "danger" },
  { value: "REOPENED", label: "Reopened", tone: "primary" },
  { value: "COMPLETED", label: "Completed", tone: "success" },
  { value: "CANCELLED", label: "Cancelled", tone: "neutral" },
];

export const STATUS_META = Object.fromEntries(STATUSES.map((s) => [s.value, s])) as Record<
  TaskStatus,
  (typeof STATUSES)[number]
>;

export const PRIORITIES: { value: TaskPriority; label: string }[] = [
  { value: "URGENT", label: "Urgent" },
  { value: "HIGH", label: "High" },
  { value: "MEDIUM", label: "Medium" },
  { value: "LOW", label: "Low" },
];

export function StatusBadge({ status }: { status: TaskStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge tone={meta.tone} className={cn(status === "CANCELLED" && "line-through")}>
      {meta.label}
    </Badge>
  );
}

const PRIORITY_ICON = { URGENT: AlertOctagon, HIGH: ChevronsUp, MEDIUM: Minus, LOW: ArrowDown } as const;
const PRIORITY_TONE: Record<TaskPriority, string> = {
  URGENT: "text-danger",
  HIGH: "text-warning",
  MEDIUM: "text-muted",
  LOW: "text-info",
};

export function PriorityBadge({ priority, compact }: { priority: TaskPriority; compact?: boolean }) {
  const Icon = PRIORITY_ICON[priority] ?? ArrowUp;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-semibold", PRIORITY_TONE[priority])}>
      <Icon className="size-3.5" aria-hidden />
      {compact ? <span className="sr-only">{priority} priority</span> : PRIORITIES.find((p) => p.value === priority)?.label}
    </span>
  );
}
