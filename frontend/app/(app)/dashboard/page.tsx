"use client";

import { format, subDays } from "date-fns";
import { ArrowRight, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BarChartCard, ProgressList } from "@/components/common/bar-chart";
import { useRunningTimer } from "@/components/layout/timer-bar";
import { STATUS_META } from "@/components/tasks/meta";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Card, CardHeader, Stat, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { ErrorState, LoadingRows, PageHeader } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { useMe, useSession } from "@/lib/auth/session";
import { formatClock } from "@/lib/utils";

const RANGES = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
];

function ManagerDashboard() {
  const [days, setDays] = useState(30);
  const [project, setProject] = useState("");
  const projects = $api.useQuery("get", "/api/v1/org/projects/", { params: { query: { page_size: 100 } } });
  const today = new Date();
  const summary = $api.useQuery("get", "/api/v1/dashboards/manager/", {
    params: { query: {
      date_from: format(subDays(today, days - 1), "yyyy-MM-dd"),
      date_to: format(today, "yyyy-MM-dd"),
      project: project || undefined,
    } },
  });
  const hours = (v: number) => `${v}h`;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Select aria-label="Period" className="sm:w-48" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </Select>
        <Select aria-label="Project" className="sm:w-64" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">All my projects</option>
          {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.key} · {p.name}</option>)}
        </Select>
      </div>
      {!summary.data ? (summary.isPending ? <LoadingRows rows={4} /> : <ErrorState error={summary.error} onRetry={() => summary.refetch()} />) : (() => {
        const d = summary.data;
        const t = d.totals as Record<string, number>;
        const statusData = (["backlog", "assigned", "in_progress", "pending_review", "blocked", "on_hold", "completed"] as const)
          .map((k) => ({ label: { backlog: "Backlog", assigned: "Assigned", in_progress: "In progress", pending_review: "In review",
            blocked: "Blocked", on_hold: "On hold", completed: "Completed" }[k], value: t[k] ?? 0 }));
        const workload = (d.workload as { name: string; open_tasks: number }[]).map((w) => ({ label: w.name, value: w.open_tasks }));
        const productivity = d.productivity as { name: string; completed: number; on_time_rate: number | null; logged_hours: number }[];
        return (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="Total tasks" value={t.total} />
              <Stat label="In progress" value={t.in_progress} />
              <Stat label="Waiting review" value={t.pending_review} />
              <Stat label="Blocked" value={t.blocked} tone={t.blocked ? "danger" : "primary"} />
              <Stat label="Overdue" value={t.overdue} tone={t.overdue ? "danger" : "primary"} />
              <Stat label="Completed" value={t.completed_in_period} hint="in this period" />
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <BarChartCard title="Tasks by status" description="Current state of all tasks in scope" data={statusData} />
              <BarChartCard title="Open tasks per person" description="Workload distribution" data={workload} horizontal
                            emptyText="Nobody has open work" />
              <BarChartCard title="Hours by person" description="Logged in this period" horizontal format={hours}
                            data={d.time_by_employee.map((r) => ({ label: r.name ?? "—", value: r.hours }))} />
              <BarChartCard title="Hours by project" description="Logged in this period" horizontal format={hours}
                            data={d.time_by_project.map((r) => ({ label: r.key ?? "—", value: r.hours }))} />
              <ProgressList title="Project progress"
                            items={(d.project_progress as { key: string; name: string; completed: number; total: number }[])
                              .map((p) => ({ label: `${p.key} · ${p.name}`, done: p.completed, total: p.total }))} />
              <Card>
                <CardHeader title="Productivity" description="Completed tasks, on-time rate and hours in this period" />
                {productivity.length === 0 ? <p className="px-5 py-6 text-sm text-muted">No tasks completed in this period.</p> : (
                  <table className="w-full text-sm">
                    <caption className="sr-only">Productivity by person</caption>
                    <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                      <th scope="col" className="px-5 py-2.5">Person</th>
                      <th scope="col" className="px-2 py-2.5 text-right">Done</th>
                      <th scope="col" className="px-2 py-2.5 text-right">On time</th>
                      <th scope="col" className="px-5 py-2.5 text-right">Hours</th>
                    </tr></thead>
                    <tbody>
                      {productivity.map((p) => (
                        <tr key={p.name} className="border-b border-line last:border-0">
                          <th scope="row" className="px-5 py-2.5 text-left font-semibold text-ink">{p.name}</th>
                          <td className="px-2 py-2.5 text-right tabular-nums">{p.completed}</td>
                          <td className="px-2 py-2.5 text-right tabular-nums">{p.on_time_rate === null ? "—" : `${p.on_time_rate}%`}</td>
                          <td className="px-5 py-2.5 text-right tabular-nums">{p.logged_hours}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            </div>
          </>
        );
      })()}
    </div>
  );
}

function MemberDashboard() {
  const summary = $api.useQuery("get", "/api/v1/dashboards/member/");
  const { entry, elapsed } = useRunningTimer();
  if (!summary.data) return summary.isPending ? <LoadingRows rows={3} /> : <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  const d = summary.data;
  const statusData = Object.entries(d.by_status)
    .filter(([s, n]) => n > 0 && s !== "CANCELLED")
    .map(([s, n]) => ({ label: STATUS_META[s as keyof typeof STATUS_META].label, value: n }));
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Open tasks" value={d.open} />
        <Stat label="Due in 7 days" value={d.due_soon} />
        <Stat label="Overdue" value={d.overdue} tone={d.overdue ? "danger" : "primary"} />
        <Stat label="Changes requested" value={d.changes_requested} tone={d.changes_requested ? "danger" : "primary"} />
        <Stat label="Hours today" value={d.hours_today} />
        <Stat label="Hours this week" value={d.hours_this_week} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="flex flex-col justify-between gap-4 p-5">
          <div>
            <p className="text-sm font-semibold text-muted">Timer</p>
            {entry ? (
              <>
                <p className="mt-1 font-mono text-3xl font-extrabold tabular-nums text-ink">{formatClock(elapsed)}</p>
                <p className="truncate text-sm text-muted">{entry.task.key} {entry.task.title}</p>
              </>
            ) : <p className="mt-1 text-ink">No timer running. Start one from a task.</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild><Link href="/my-tasks">My tasks <ArrowRight /></Link></Button>
            {d.reviews_waiting_for_me > 0 && <Button asChild variant="outline"><Link href="/reviews">{d.reviews_waiting_for_me} review(s) waiting</Link></Button>}
          </div>
        </Card>
        <BarChartCard title="My tasks by status" data={statusData} emptyText="Nothing assigned yet" />
      </div>
    </div>
  );
}

function HrDashboard() {
  const query = (status: "ACTIVE" | "INVITED" | "DEACTIVATED") => ({ params: { query: { status: [status], page_size: 1 } } });
  const active = $api.useQuery("get", "/api/v1/hr/employees/", query("ACTIVE"));
  const invited = $api.useQuery("get", "/api/v1/hr/employees/", query("INVITED"));
  const deactivated = $api.useQuery("get", "/api/v1/hr/employees/", query("DEACTIVATED"));
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat label="Active employees" value={active.data?.count ?? "—"} />
        <Stat label="Pending invites" value={invited.data?.count ?? "—"} />
        <Stat label="Deactivated" value={deactivated.data?.count ?? "—"} />
      </div>
      <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-primary-100 text-primary-600"><Users className="size-5" /></span>
          <div>
            <p className="font-bold text-ink">People and organization</p>
            <p className="text-sm text-muted">Add employees, resend invite links, manage teams, holidays and leave.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button asChild><Link href="/hr/employees">People</Link></Button>
          <Button asChild variant="outline"><Link href="/hr/org">Organization</Link></Button>
        </div>
      </Card>
    </div>
  );
}

export default function DashboardPage() {
  const me = useMe();
  const { can } = useSession();
  const tabs = [
    can("dashboard.manager.view") && { value: "team", label: "Team overview", body: <ManagerDashboard /> },
    can("dashboard.member.view") && { value: "me", label: "My work", body: <MemberDashboard /> },
    can("employee.create") && { value: "hr", label: "People", body: <HrDashboard /> },
  ].filter(Boolean) as { value: string; label: string; body: React.ReactNode }[];
  return (
    <>
      <PageHeader title={`Hello, ${me.first_name}`} description={me.company?.name} />
      {tabs.length === 1 ? tabs[0].body : tabs.length > 1 ? (
        <Tabs defaultValue={tabs[0].value}>
          <TabsList className="mb-5">{tabs.map((t) => <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>)}</TabsList>
          {tabs.map((t) => <TabsContent key={t.value} value={t.value}>{t.body}</TabsContent>)}
        </Tabs>
      ) : <p className="text-muted">Nothing to show for your role yet.</p>}
    </>
  );
}
