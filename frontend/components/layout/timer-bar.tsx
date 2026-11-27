"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Square, Timer } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { $api } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session";
import { cn, formatClock } from "@/lib/utils";

export const TIMER_QUERY = ["get", "/api/v1/time/timer/current/"] as const;

/** Elapsed seconds computed from the server's start time and the server clock offset,
 * so the timer is right across refreshes, devices and wrong local clocks. */
export function useRunningTimer() {
  const { can } = useSession();
  const query = $api.useQuery("get", "/api/v1/time/timer/current/", undefined, {
    enabled: can("time.track"),
    refetchInterval: 60_000,
  });
  const entry = query.data?.entry ?? null;
  const offset = useMemo(
    () => (query.data ? new Date(query.data.server_time).getTime() - query.dataUpdatedAt : 0),
    [query.data, query.dataUpdatedAt],
  );
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!entry) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [entry]);
  const elapsed = entry ? (now + offset - new Date(entry.started_at).getTime()) / 1000 : 0;
  return { entry, elapsed, query };
}

export function useTimerActions() {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: TIMER_QUERY });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/{task_id}/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/"] });
  };
  const options = { onSuccess: invalidate };
  return {
    start: $api.useMutation("post", "/api/v1/time/timer/start/", {
      ...options,
      onSuccess: () => {
        invalidate();
        toast.success("Timer started");
      },
    }),
    switchTo: $api.useMutation("post", "/api/v1/time/timer/switch/", options),
    pause: $api.useMutation("post", "/api/v1/time/timer/pause/", options),
    resume: $api.useMutation("post", "/api/v1/time/timer/resume/", options),
    stop: $api.useMutation("post", "/api/v1/time/timer/stop/", {
      ...options,
      onSuccess: () => {
        invalidate();
        toast.success("Time logged");
      },
    }),
  };
}

/** Global running-timer bar: sticky top on desktop, above the bottom nav on phones. */
export function TimerBar() {
  const { entry, elapsed } = useRunningTimer();
  const { pause, stop } = useTimerActions();
  if (!entry) return null;
  return (
    <div
      role="status"
      aria-label="Running timer"
      className={cn(
        "fixed inset-x-3 bottom-[76px] z-30 flex items-center gap-3 rounded-2xl border border-primary-200 bg-surface/95 px-3 py-2 shadow-card backdrop-blur",
        "md:sticky md:inset-x-auto md:top-0 md:bottom-auto md:mx-0 md:rounded-none md:border-x-0 md:border-t-0 md:px-6 md:shadow-none",
      )}
    >
      <span className="relative grid size-8 place-items-center rounded-full bg-primary-100 text-primary-600">
        <Timer className="size-4" aria-hidden />
        <span className="absolute -top-0.5 -right-0.5 size-2.5 animate-pulse rounded-full bg-success" />
      </span>
      <div className="min-w-0 flex-1">
        <Link href={`/tasks/${entry.task.id}`} className="block truncate text-sm font-semibold text-ink hover:underline">
          <span className="text-muted">{entry.task.key}</span> {entry.task.title}
        </Link>
      </div>
      <span className="font-mono text-base font-bold tabular-nums text-ink" aria-live="off">
        {formatClock(elapsed)}
      </span>
      <Button size="icon" variant="outline" aria-label="Pause timer" loading={pause.isPending} onClick={() => pause.mutate({})}>
        {!pause.isPending && <Pause />}
      </Button>
      <Button
        size="icon"
        variant="danger"
        aria-label="Stop timer"
        loading={stop.isPending}
        onClick={() => stop.mutate({ body: { note: "" } })}
      >
        {!stop.isPending && <Square />}
      </Button>
    </div>
  );
}

/** Start/stop control for one task (task detail, task cards). */
export function TaskTimerButton({ taskId, size = "md" }: { taskId: string; size?: "sm" | "md" }) {
  const { entry } = useRunningTimer();
  const { start, switchTo, stop } = useTimerActions();
  const runningHere = entry?.task.id === taskId;
  if (runningHere) {
    return (
      <Button size={size} variant="danger" loading={stop.isPending} onClick={() => stop.mutate({ body: { note: "" } })}>
        <Square /> Stop timer
      </Button>
    );
  }
  if (entry) {
    return (
      <Button
        size={size}
        variant="outline"
        loading={switchTo.isPending}
        onClick={() => switchTo.mutate({ body: { task_id: taskId } })}
      >
        <Play /> Switch timer here
      </Button>
    );
  }
  return (
    <Button size={size} loading={start.isPending} onClick={() => start.mutate({ body: { task_id: taskId } })}>
      <Play /> Start timer
    </Button>
  );
}
