"use client";

import { Table2 } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";

export type BarDatum = { label: string; value: number };

function ChartTooltip({ active, payload, format }: { active?: boolean; payload?: { payload: BarDatum }[]; format: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-sm shadow-card">
      <p className="font-semibold text-ink">{d.label}</p>
      <p className="text-muted">{format(d.value)}</p>
    </div>
  );
}

/**
 * Single-series bar chart (one hue: chart slot 1), thin bars with rounded data ends,
 * recessive grid, value labels on every bar, hover tooltip, and a table view toggle,
 * so the data never depends on colour alone. Horizontal layout suits long names.
 */
export function BarChartCard({
  title,
  description,
  data,
  format = (v) => String(v),
  horizontal = false,
  emptyText = "No data for this period",
}: {
  title: string;
  description?: string;
  data: BarDatum[];
  format?: (v: number) => string;
  horizontal?: boolean;
  emptyText?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const height = horizontal ? Math.max(160, data.length * 36 + 40) : 260;
  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        action={data.length > 0 && (
          <Button variant="ghost" size="sm" aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}>
            <Table2 /> {asTable ? "Chart" : "Table"}
          </Button>
        )}
      />
      {data.length === 0 ? (
        <EmptyState title={emptyText} />
      ) : asTable ? (
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <tbody>
            {data.map((d) => (
              <tr key={d.label} className="border-b border-line last:border-0">
                <th scope="row" className="px-5 py-2 text-left font-medium text-ink">{d.label}</th>
                <td className="px-5 py-2 text-right font-semibold tabular-nums text-ink">{format(d.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="px-2 py-4" role="img" aria-label={`${title}: ${data.map((d) => `${d.label} ${format(d.value)}`).join(", ")}`}>
          <ResponsiveContainer width="100%" height={height}>
            <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"}
                      margin={{ top: 16, right: horizontal ? 48 : 8, bottom: 4, left: horizontal ? 8 : -12 }}>
              <CartesianGrid stroke="var(--tt-chart-grid)" vertical={horizontal} horizontal={!horizontal} />
              {horizontal ? (
                <>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="label" width={120} tickLine={false} axisLine={false}
                         tick={{ fill: "var(--tt-muted)", fontSize: 12 }} />
                </>
              ) : (
                <>
                  <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--tt-line)" }} interval={0}
                         tick={{ fill: "var(--tt-muted)", fontSize: 12 }} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--tt-muted)", fontSize: 12 }} />
                </>
              )}
              <Tooltip cursor={{ fill: "var(--tt-hover)" }} content={<ChartTooltip format={format} />} />
              <Bar dataKey="value" fill="var(--tt-chart-1)" maxBarSize={horizontal ? 18 : 36}
                   radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="value" position={horizontal ? "right" : "top"} formatter={(v: unknown) => format(Number(v))}
                           style={{ fill: "var(--tt-ink)", fontSize: 12, fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

/** Project completion as labelled progress meters (a chart is overkill for a single ratio). */
export function ProgressList({ title, items }: { title: string; items: { label: string; done: number; total: number }[] }) {
  return (
    <Card>
      <CardHeader title={title} />
      {items.length === 0 ? <EmptyState title="No projects yet" /> : (
        <ul className="flex flex-col gap-4 p-5">
          {items.map((i) => {
            const pct = i.total ? Math.round((i.done / i.total) * 100) : 0;
            return (
              <li key={i.label}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-semibold text-ink">{i.label}</span>
                  <span className="tabular-nums text-muted">{i.done}/{i.total} · {pct}%</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct}
                     aria-valuemin={0} aria-valuemax={100} aria-label={`${i.label} ${pct}% complete`}>
                  <div className="h-full rounded-full bg-[var(--tt-chart-1)]" style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
