"use client";

import { Table2 } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { BarChartCard } from "@/components/common/bar-chart";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import type { components } from "@/lib/api/schema";
import { formatDate } from "@/lib/utils";

export type TaskHoursRow = components["schemas"]["TimeTaskRow"];

/** Top tasks get the fixed categorical slots in order; everything else folds into "Other". */
const TOP_TASKS = 5;
const SLOTS = ["var(--tt-chart-1)", "var(--tt-chart-2)", "var(--tt-chart-3)", "var(--tt-chart-4)", "var(--tt-chart-5)"];
const OTHER = "__other__";
const OTHER_COLOR = "var(--tt-muted)";

const round = (n: number) => Math.round(n * 100) / 100;
const hrs = (n: number) => `${round(n)}h`;

type TaskInfo = { id: string; key: string; title: string; hours: number };

function taskTotals(rows: TaskHoursRow[]): TaskInfo[] {
  const map = new Map<string, TaskInfo>();
  for (const r of rows) {
    const t = map.get(r.task_id) ?? { id: r.task_id, key: r.task_key, title: r.task_title, hours: 0 };
    t.hours += r.hours;
    map.set(r.task_id, t);
  }
  return [...map.values()].sort((a, b) => b.hours - a.hours);
}

export function TaskHoursStats({ rows }: { rows: TaskHoursRow[] }) {
  const total = rows.reduce((s, r) => s + r.hours, 0);
  const people = new Set(rows.map((r) => r.user_id)).size;
  const tasks = new Set(rows.map((r) => r.task_id)).size;
  const days = new Set(rows.map((r) => r.work_date)).size;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="Total hours" value={hrs(total)} />
      <Stat label="People" value={people} />
      <Stat label="Tasks worked on" value={tasks} />
      <Stat label="Avg hours per active day" value={days ? hrs(total / days) : "0h"} hint={`${days} active day${days === 1 ? "" : "s"}`} />
    </div>
  );
}

type StackTooltipProps = {
  active?: boolean;
  label?: string;
  payload?: { dataKey: string; value: number; color: string }[];
  names: Map<string, string>;
};

function StackTooltip({ active, label, payload, names }: StackTooltipProps) {
  if (!active || !payload?.length) return null;
  const items = payload.filter((p) => p.value > 0);
  const total = items.reduce((s, p) => s + p.value, 0);
  return (
    <div className="max-w-xs rounded-xl border border-line bg-surface px-3 py-2 text-sm shadow-card">
      <p className="font-semibold text-ink">{label} · {hrs(total)}</p>
      <ul className="mt-1 flex flex-col gap-0.5">
        {items.map((p) => (
          <li key={p.dataKey} className="flex items-center gap-2 text-muted">
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: p.color }} aria-hidden />
            <span className="truncate">{names.get(p.dataKey)}</span>
            <span className="ml-auto pl-3 font-semibold tabular-nums text-ink">{hrs(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Hours per member, each bar split by the task the time was logged on. */
export function MemberTaskChart({ rows }: { rows: TaskHoursRow[] }) {
  const [asTable, setAsTable] = useState(false);
  const { data, series, names } = useMemo(() => {
    const tasks = taskTotals(rows);
    const top = tasks.slice(0, TOP_TASKS);
    const topIds = new Set(top.map((t) => t.id));
    const names = new Map<string, string>(top.map((t) => [t.id, `${t.key} ${t.title}`]));
    const hasOther = tasks.length > TOP_TASKS;
    if (hasOther) names.set(OTHER, `Other tasks (${tasks.length - TOP_TASKS})`);
    const byMember = new Map<string, Record<string, number | string>>();
    for (const r of rows) {
      const m = byMember.get(r.user_id) ?? { member: r.member, total: 0 };
      const k = topIds.has(r.task_id) ? r.task_id : OTHER;
      m[k] = round(((m[k] as number) ?? 0) + r.hours);
      m.total = round((m.total as number) + r.hours);
      byMember.set(r.user_id, m);
    }
    const data = [...byMember.values()].sort((a, b) => (b.total as number) - (a.total as number));
    const series = [
      ...top.map((t, i) => ({ key: t.id, color: SLOTS[i] })),
      ...(hasOther ? [{ key: OTHER, color: OTHER_COLOR }] : []),
    ];
    return { data, series, names };
  }, [rows]);

  const title = "Hours by employee and task";
  const height = Math.max(160, data.length * 40 + 80);
  return (
    <Card>
      <CardHeader
        title={title}
        description={`Each bar is split by task (top ${TOP_TASKS} tasks by hours)`}
        action={data.length > 0 && (
          <Button variant="ghost" size="sm" aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}>
            <Table2 /> {asTable ? "Chart" : "Table"}
          </Button>
        )}
      />
      {data.length === 0 ? (
        <EmptyState title="No time logged in this range" />
      ) : asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{title}</caption>
            <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th scope="col" className="px-5 py-2.5">Employee</th>
              {series.map((s) => <th key={s.key} scope="col" className="px-3 py-2.5 text-right">{names.get(s.key)}</th>)}
              <th scope="col" className="px-5 py-2.5 text-right">Total</th>
            </tr></thead>
            <tbody>{data.map((d) => (
              <tr key={d.member as string} className="border-b border-line last:border-0">
                <th scope="row" className="px-5 py-2 text-left font-semibold text-ink">{d.member}</th>
                {series.map((s) => <td key={s.key} className="px-3 py-2 text-right tabular-nums">{d[s.key] ? hrs(d[s.key] as number) : "–"}</td>)}
                <td className="px-5 py-2 text-right font-semibold tabular-nums text-ink">{hrs(d.total as number)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : (
        <div className="px-2 py-4" role="img"
             aria-label={`${title}: ${data.map((d) => `${d.member} ${hrs(d.total as number)}`).join(", ")}`}>
          <ResponsiveContainer width="100%" height={height}>
            <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, bottom: 4, left: 8 }}>
              <CartesianGrid stroke="var(--tt-chart-grid)" horizontal={false} />
              <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={(v) => `${v}h`}
                     tick={{ fill: "var(--tt-muted)", fontSize: 12 }} />
              <YAxis type="category" dataKey="member" width={130} tickLine={false} axisLine={false}
                     tick={{ fill: "var(--tt-muted)", fontSize: 12 }} />
              <Tooltip cursor={{ fill: "var(--tt-hover)" }} content={<StackTooltip names={names} />} />
              <Legend verticalAlign="top" align="left" iconType="square" iconSize={10}
                      wrapperStyle={{ fontSize: 12, paddingBottom: 8, color: "var(--tt-muted)" }}
                      formatter={(key: string) => <span className="text-muted">{names.get(key)}</span>} />
              {series.map((s, i) => (
                <Bar key={s.key} dataKey={s.key} stackId="hours" fill={s.color} maxBarSize={20}
                     stroke="var(--tt-surface)" strokeWidth={2} isAnimationActive={false}
                     radius={i === series.length - 1 ? [0, 4, 4, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

/** Total hours per task across everyone in range. */
export function TaskTotalsChart({ rows }: { rows: TaskHoursRow[] }) {
  const data = useMemo(
    () => taskTotals(rows).slice(0, 15).map((t) => ({ label: `${t.key} ${t.title}`, value: round(t.hours) })),
    [rows],
  );
  return <BarChartCard horizontal title="Hours by task" description="Top 15 tasks in range" data={data} format={hrs}
                       emptyText="No time logged in this range" />;
}

/** Audit log: employee > task > day, with subtotals per employee and per task. */
export function TaskLogTable({ rows }: { rows: TaskHoursRow[] }) {
  const groups = useMemo(() => {
    const byMember = new Map<string, { member: string; hours: number; tasks: Map<string, { key: string; title: string; project: string; hours: number; days: TaskHoursRow[] }> }>();
    for (const r of rows) {
      const m = byMember.get(r.user_id) ?? { member: r.member, hours: 0, tasks: new Map() };
      const t = m.tasks.get(r.task_id) ?? { key: r.task_key, title: r.task_title, project: r.project_key, hours: 0, days: [] };
      t.hours += r.hours;
      t.days.push(r);
      m.hours += r.hours;
      m.tasks.set(r.task_id, t);
      byMember.set(r.user_id, m);
    }
    return [...byMember.entries()]
      .map(([id, m]) => ({ id, ...m, tasks: [...m.tasks.entries()].sort((a, b) => b[1].hours - a[1].hours) }))
      .sort((a, b) => b.hours - a.hours);
  }, [rows]);

  return (
    <Card>
      <CardHeader title="Task time log" description="Who worked on which task, on which day" />
      {groups.length === 0 ? (
        <EmptyState title="No time logged in this range" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Hours per employee, task and day</caption>
            <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th scope="col" className="px-5 py-2.5">Employee / Task</th>
              <th scope="col" className="px-3 py-2.5">Project</th>
              <th scope="col" className="px-3 py-2.5">Day</th>
              <th scope="col" className="px-3 py-2.5 text-right">Hours</th>
              <th scope="col" className="px-5 py-2.5 text-right">Entries</th>
            </tr></thead>
            <tbody>
              {groups.map((g) => (
                <Fragment key={g.id}>
                  <tr className="border-b border-line bg-surface-2">
                    <th scope="rowgroup" colSpan={3} className="px-5 py-2 text-left font-bold text-ink">{g.member}</th>
                    <td className="px-3 py-2 text-right font-bold tabular-nums text-ink">{hrs(g.hours)}</td>
                    <td className="px-5 py-2" />
                  </tr>
                  {g.tasks.map(([taskId, t]) => (
                    <Fragment key={taskId}>
                      <tr className="border-b border-line">
                        <td className="py-2 pl-8 pr-3 font-semibold text-ink">
                          <span className="tabular-nums text-muted">{t.key}</span> {t.title}
                        </td>
                        <td className="px-3 py-2">{t.project}</td>
                        <td className="px-3 py-2 text-muted">{t.days.length} day{t.days.length === 1 ? "" : "s"}</td>
                        <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">{hrs(t.hours)}</td>
                        <td className="px-5 py-2" />
                      </tr>
                      {t.days.map((d) => (
                        <tr key={d.work_date} className="border-b border-line last:border-0 text-muted">
                          <td className="py-1.5 pl-12 pr-3" colSpan={2} />
                          <td className="px-3 py-1.5">{formatDate(d.work_date)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{hrs(d.hours)}</td>
                          <td className="px-5 py-1.5 text-right tabular-nums">{d.entries}</td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
