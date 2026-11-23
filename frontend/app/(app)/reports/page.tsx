"use client";

import { useQueryClient } from "@tanstack/react-query";
import { format, subDays } from "date-fns";
import { CalendarClock, Download, FileSpreadsheet, FileText, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { BarChartCard } from "@/components/common/bar-chart";
import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { MemberTaskChart, TaskHoursStats, TaskLogTable, TaskTotalsChart } from "@/components/reports/task-hours";
import { Can } from "@/components/layout/guards";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card, CardHeader, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api, downloadFile } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cleanParams, formatBytes, formatDate, formatDateTime, titleCase } from "@/lib/utils";

type ReportType = "time" | "tasks";
type Filters = { report: ReportType; group_by: "member" | "team" | "project"; period: "daily" | "weekly" | "monthly";
  date_from: string; date_to: string; project: string; team: string };
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function useFilterOptions() {
  const projects = $api.useQuery("get", "/api/v1/org/projects/", { params: { query: { page_size: 100 } } });
  const teams = $api.useQuery("get", "/api/v1/org/teams/", { params: { query: { page_size: 100 } } });
  return { projects: projects.data?.results ?? [], teams: teams.data?.results ?? [] };
}

function ReportFilters({ value, onChange }: { value: Filters; onChange: (f: Filters) => void }) {
  const { projects, teams } = useFilterOptions();
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-2 lg:grid-cols-7">
      <Field label="Report" htmlFor="r-type">
        <Select value={value.report} onChange={(e) => set("report", e.target.value as ReportType)}>
          <option value="time">Hours logged</option><option value="tasks">Tasks</option>
        </Select>
      </Field>
      <Field label="Group by" htmlFor="r-group">
        <Select value={value.group_by} onChange={(e) => set("group_by", e.target.value as Filters["group_by"])}>
          <option value="member">Member</option><option value="team">Team</option><option value="project">Project</option>
        </Select>
      </Field>
      <Field label="Period" htmlFor="r-period">
        <Select value={value.period} onChange={(e) => set("period", e.target.value as Filters["period"])}>
          <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
        </Select>
      </Field>
      <Field label="From" htmlFor="r-from"><Input type="date" value={value.date_from} onChange={(e) => set("date_from", e.target.value)} /></Field>
      <Field label="To" htmlFor="r-to"><Input type="date" value={value.date_to} onChange={(e) => set("date_to", e.target.value)} /></Field>
      <Field label="Project" htmlFor="r-project">
        <Select value={value.project} onChange={(e) => set("project", e.target.value)}>
          <option value="">All</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.key}</option>)}
        </Select>
      </Field>
      <Field label="Team" htmlFor="r-team">
        <Select value={value.team} onChange={(e) => set("team", e.target.value)}>
          <option value="">All</option>{teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      </Field>
    </div>
  );
}

function ExportButtons({ filters }: { filters: Filters }) {
  const qc = useQueryClient();
  const exportIt = $api.useMutation("post", "/api/v1/reports/exports/", {
    onSuccess: () => {
      toast.success("Export started. It appears under Exports when ready.");
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/reports/exports/"] });
    },
  });
  const run = (fmt: "csv" | "xlsx" | "pdf") => {
    const { report, project, team, ...rest } = filters;
    exportIt.mutate({ body: { ...rest, ...cleanParams({ project, team }), report_type: report, format: fmt } });
  };
  return (
    <Can anyOf={["report.export"]}>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={exportIt.isPending} onClick={() => run("csv")}><FileText /> CSV</Button>
        <Button variant="outline" size="sm" disabled={exportIt.isPending} onClick={() => run("xlsx")}><FileSpreadsheet /> Excel</Button>
        <Button variant="outline" size="sm" disabled={exportIt.isPending} onClick={() => run("pdf")}><FileText /> PDF</Button>
      </div>
    </Can>
  );
}

function ReportView() {
  const today = new Date();
  const [filters, setFilters] = useState<Filters>({
    report: "time", group_by: "member", period: "weekly",
    date_from: format(subDays(today, 29), "yyyy-MM-dd"), date_to: format(today, "yyyy-MM-dd"), project: "", team: "",
  });
  const query = cleanParams({ group_by: filters.group_by, period: filters.period, date_from: filters.date_from,
    date_to: filters.date_to, project: filters.project, team: filters.team });
  const time = $api.useQuery("get", "/api/v1/reports/time/", { params: { query } }, { enabled: filters.report === "time" });
  const tasks = $api.useQuery("get", "/api/v1/reports/tasks/", { params: { query } }, { enabled: filters.report === "tasks" });
  const byTask = $api.useQuery("get", "/api/v1/reports/time/tasks/", { params: { query } }, { enabled: filters.report === "time" });
  const totals = useMemo(() => {
    const map = new Map<string, number>();
    if (filters.report === "time") for (const r of time.data ?? []) map.set(r.group, (map.get(r.group) ?? 0) + r.hours);
    else for (const r of tasks.data ?? []) map.set(r.group, (map.get(r.group) ?? 0) + r.completed);
    return [...map.entries()].map(([label, value]) => ({ label, value: Math.round(value * 100) / 100 })).sort((a, b) => b.value - a.value);
  }, [filters.report, time.data, tasks.data]);
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <ReportFilters value={filters} onChange={setFilters} />
        <div className="flex justify-end p-3"><ExportButtons filters={filters} /></div>
      </Card>
      {filters.report === "time" && (
        <QueryState query={byTask}>
          {(rows) => (
            <>
              <TaskHoursStats rows={rows} />
              <MemberTaskChart rows={rows} />
              <TaskTotalsChart rows={rows} />
            </>
          )}
        </QueryState>
      )}
      <BarChartCard horizontal title={filters.report === "time" ? "Hours in range" : "Tasks completed in range"}
                    description={`By ${filters.group_by}`} data={totals.slice(0, 15)}
                    format={filters.report === "time" ? (v) => `${v}h` : undefined} />
      <Card>
        <CardHeader title="Breakdown" description={`${titleCase(filters.period)} buckets`} />
        {filters.report === "time" ? (
          <QueryState query={time} isEmpty={(d) => !d.length} empty={<EmptyState title="No time logged in this range" />}>
            {(rows) => (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">Hours report</caption>
                  <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th scope="col" className="px-5 py-2.5">{titleCase(filters.group_by)}</th><th scope="col" className="px-3 py-2.5">Period</th>
                    <th scope="col" className="px-3 py-2.5 text-right">Hours</th><th scope="col" className="px-5 py-2.5 text-right">Entries</th>
                  </tr></thead>
                  <tbody>{rows.map((r, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      <td className="px-5 py-2 font-semibold text-ink">{r.group}</td><td className="px-3 py-2">{formatDate(r.period_start)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.hours}</td><td className="px-5 py-2 text-right tabular-nums">{r.entries}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            )}
          </QueryState>
        ) : (
          <QueryState query={tasks} isEmpty={(d) => !d.length} empty={<EmptyState title="No task activity in this range" />}>
            {(rows) => (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">Task report</caption>
                  <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th scope="col" className="px-5 py-2.5">{titleCase(filters.group_by)}</th><th scope="col" className="px-3 py-2.5">Period</th>
                    <th scope="col" className="px-3 py-2.5 text-right">Created</th><th scope="col" className="px-3 py-2.5 text-right">Completed</th>
                    <th scope="col" className="px-5 py-2.5 text-right">On time</th>
                  </tr></thead>
                  <tbody>{rows.map((r, i) => (
                    <tr key={i} className="border-b border-line last:border-0">
                      <td className="px-5 py-2 font-semibold text-ink">{r.group}</td><td className="px-3 py-2">{formatDate(r.period_start)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.created}</td><td className="px-3 py-2 text-right tabular-nums">{r.completed}</td>
                      <td className="px-5 py-2 text-right tabular-nums">{r.completed_on_time}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            )}
          </QueryState>
        )}
      </Card>
      {filters.report === "time" && byTask.data && <TaskLogTable rows={byTask.data} />}
    </div>
  );
}

function Exports() {
  const exports = $api.useQuery("get", "/api/v1/reports/exports/", undefined, {
    refetchInterval: (q) => (q.state.data?.results.some((e) => e.status === "QUEUED" || e.status === "RUNNING") ? 3000 : false),
  });
  return (
    <Card>
      <CardHeader title="Exports" description="Files are kept for 7 days." />
      <QueryState query={exports} isEmpty={(d) => !d.results.length} empty={<EmptyState title="No exports yet" description="Use CSV, Excel or PDF on the report tab." />}>
        {(data) => (
          <ul className="divide-y divide-line">
            {data.results.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">{titleCase(e.report_type ?? "")} report · {(e.format ?? "").toUpperCase()}</p>
                  <p className="text-xs text-muted">{formatDateTime(e.created_at)}{e.status === "READY" && ` · ${e.row_count} rows · ${formatBytes(e.size_bytes ?? 0)}`}</p>
                  {e.error && <p className="text-xs text-danger">{e.error}</p>}
                </div>
                <Badge tone={e.status === "READY" ? "success" : e.status === "FAILED" ? "danger" : "info"}>{titleCase(e.status ?? "")}</Badge>
                {e.status === "READY" && (
                  <Button variant="outline" size="sm"
                          onClick={() => void downloadFile(`/api/v1/reports/exports/${e.id}/download/`, e.filename ?? "report").catch((err) => toast.error(errorMessage(err)))}>
                    <Download /> Download
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Card>
  );
}

type Schedule = components["schemas"]["ScheduleOutput"];

function ScheduleDialog({ schedule, onClose }: { schedule: Schedule | "new"; onClose: () => void }) {
  const qc = useQueryClient();
  const s = schedule === "new" ? null : schedule;
  const [name, setName] = useState(s?.name ?? "Weekly hours");
  const [reportType, setReportType] = useState<ReportType>((s?.report_type as ReportType) ?? "time");
  const [fmt, setFmt] = useState<"csv" | "xlsx" | "pdf">((s?.format as "xlsx") ?? "xlsx");
  const [frequency, setFrequency] = useState<"DAILY" | "WEEKLY" | "MONTHLY">((s?.frequency as "WEEKLY") ?? "WEEKLY");
  const [sendAt, setSendAt] = useState(s?.send_at?.slice(0, 5) ?? "08:00");
  const [weekday, setWeekday] = useState(s?.weekday ?? 0);
  const [day, setDay] = useState(s?.day_of_month ?? 1);
  const [groupBy, setGroupBy] = useState(((s?.filters as Record<string, string>)?.group_by as Filters["group_by"]) ?? "member");
  const [active, setActive] = useState(s?.is_active ?? true);
  const [recipients, setRecipients] = useState<Person[]>([]);
  const done = () => { void qc.invalidateQueries({ queryKey: ["get", "/api/v1/reports/schedules/"] }); toast.success("Schedule saved"); onClose(); };
  const create = $api.useMutation("post", "/api/v1/reports/schedules/", { onSuccess: done });
  const update = $api.useMutation("patch", "/api/v1/reports/schedules/{schedule_id}/", { onSuccess: done });
  const body = {
    name, report_type: reportType, format: fmt, frequency, send_at: sendAt, weekday, day_of_month: day, is_active: active,
    filters: { group_by: groupBy, period: frequency === "MONTHLY" ? "weekly" : "daily" } as never,
    ...(recipients.length ? { recipient_ids: recipients.map((r) => r.id) } : {}),
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={s ? `Edit ${s.name}` : "Schedule a report"} description="Emailed as an attachment in the company time zone.">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault();
          if (s) update.mutate({ params: { path: { schedule_id: s.id } }, body });
          else create.mutate({ body });
        }}>
          <Field label="Name" htmlFor="s-name" className="sm:col-span-2"><Input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
          <Field label="Report" htmlFor="s-type">
            <Select value={reportType} onChange={(e) => setReportType(e.target.value as ReportType)}>
              <option value="time">Hours logged</option><option value="tasks">Tasks</option></Select>
          </Field>
          <Field label="Group by" htmlFor="s-group">
            <Select value={groupBy} onChange={(e) => setGroupBy(e.target.value as Filters["group_by"])}>
              <option value="member">Member</option><option value="team">Team</option><option value="project">Project</option></Select>
          </Field>
          <Field label="Format" htmlFor="s-fmt">
            <Select value={fmt} onChange={(e) => setFmt(e.target.value as "csv")}>
              <option value="xlsx">Excel</option><option value="csv">CSV</option><option value="pdf">PDF</option></Select>
          </Field>
          <Field label="Frequency" htmlFor="s-freq">
            <Select value={frequency} onChange={(e) => setFrequency(e.target.value as "DAILY")}>
              <option value="DAILY">Daily (yesterday)</option><option value="WEEKLY">Weekly (last 7 days)</option><option value="MONTHLY">Monthly (last month)</option></Select>
          </Field>
          <Field label="Send at" htmlFor="s-at"><Input type="time" value={sendAt} onChange={(e) => setSendAt(e.target.value)} /></Field>
          {frequency === "WEEKLY" && (
            <Field label="Day" htmlFor="s-day"><Select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</Select></Field>
          )}
          {frequency === "MONTHLY" && (
            <Field label="Day of month" htmlFor="s-dom"><Input type="number" min={1} max={28} value={day} onChange={(e) => setDay(Number(e.target.value))} /></Field>
          )}
          <div className="sm:col-span-2">
            <p className="mb-1.5 text-sm font-semibold text-ink">Recipients</p>
            <p className="mb-2 text-xs text-muted">{s ? "Leave empty to keep current recipients. " : "Leave empty to send only to you. "}Recipients need company-wide report access.</p>
            <PeoplePicker label="Recipients" value={recipients} onChange={setRecipients} />
          </div>
          <label className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2.5 text-sm font-semibold sm:col-span-2">
            Active <Switch checked={active} onCheckedChange={setActive} />
          </label>
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={create.isPending || update.isPending}>Save schedule</Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Schedules() {
  const qc = useQueryClient();
  const schedules = $api.useQuery("get", "/api/v1/reports/schedules/");
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const remove = $api.useMutation("delete", "/api/v1/reports/schedules/{schedule_id}/", {
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["get", "/api/v1/reports/schedules/"] }); setDeleting(null); },
  });
  return (
    <Card>
      <CardHeader title="Scheduled reports" action={<Button size="sm" onClick={() => setEditing("new")}><Plus /> Schedule</Button>} />
      <QueryState query={schedules} isEmpty={(d) => !d.length} empty={<EmptyState icon={<CalendarClock className="size-6" />} title="No scheduled reports" />}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">{s.name} {!s.is_active && <Badge>Paused</Badge>}</p>
                  <p className="text-xs text-muted">{titleCase(s.frequency ?? "")} at {s.send_at?.slice(0, 5)} · {(s.format ?? "").toUpperCase()} · next {formatDateTime(s.next_run_at)}</p>
                  {s.last_error && <p className="text-xs text-danger">{s.last_error}</p>}
                </div>
                <Button variant="outline" size="sm" onClick={() => setEditing(s)}>Edit</Button>
                <Button variant="ghost" size="sm" aria-label={`Delete ${s.name}`} onClick={() => setDeleting(s)}><Trash2 /></Button>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {editing && <ScheduleDialog schedule={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} onOpenChange={() => setDeleting(null)} title={`Delete ${deleting?.name}?`}
                     confirmLabel="Delete" danger loading={remove.isPending}
                     onConfirm={() => deleting && remove.mutate({ params: { path: { schedule_id: deleting.id } } })} />
    </Card>
  );
}

export default function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Hours and task throughput by member, team or project." />
      <Tabs defaultValue="report">
        <TabsList className="mb-5">
          <TabsTrigger value="report">Report</TabsTrigger>
          <Can anyOf={["report.export"]}><TabsTrigger value="exports">Exports</TabsTrigger></Can>
          <Can anyOf={["report.schedule"]}><TabsTrigger value="schedules">Scheduled</TabsTrigger></Can>
        </TabsList>
        <TabsContent value="report"><ReportView /></TabsContent>
        <TabsContent value="exports"><Exports /></TabsContent>
        <TabsContent value="schedules"><Schedules /></TabsContent>
      </Tabs>
    </>
  );
}
