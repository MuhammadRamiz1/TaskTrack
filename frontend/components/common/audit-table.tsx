"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { Field, Input, Select } from "@/components/ui/form";
import { Card } from "@/components/ui/primitives";
import { EmptyState, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import type { components, operations } from "@/lib/api/schema";
import { cleanParams, formatDateTime } from "@/lib/utils";

type Entry = components["schemas"]["AuditLogOutput"];
type Category = NonNullable<NonNullable<operations["audit_list"]["parameters"]["query"]>["category"]>;
const PAGE_SIZE = 25;

const CATEGORIES: { value: Category; label: string }[] = [
  { value: "tasks", label: "Tasks and reviews" },
  { value: "organization", label: "Teams and projects" },
  { value: "people", label: "People and invitations" },
  { value: "roles", label: "Roles and access" },
  { value: "security", label: "Sign-in and security" },
  { value: "time", label: "Time tracking" },
  { value: "reports", label: "Reports" },
  { value: "settings", label: "Settings" },
];

/** Changed fields in words. Platform admins can also open the raw record. */
function Changes({ entry, raw }: { entry: Entry; raw: boolean }) {
  const [open, setOpen] = useState(false);
  const hasRaw = raw && Boolean(entry.old_value || entry.new_value);
  if (!entry.changes.length && !hasRaw) return <span className="text-muted">—</span>;
  return (
    <div>
      <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold text-link" onClick={() => setOpen((o) => !o)}
              aria-expanded={open}>
        {entry.changes.length ? `${entry.changes.length} ${entry.changes.length === 1 ? "change" : "changes"}` : "Details"}
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 flex max-w-[520px] flex-col gap-2 text-left">
          {entry.changes.length > 0 && (
            <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-3 gap-y-1 rounded-lg bg-surface-2 p-2.5 text-sm">
              {entry.changes.map((c, i) => (
                <div key={i} className="contents">
                  <dt className="font-semibold text-ink">{c.field}</dt>
                  <dd className="text-muted">
                    <span className="line-through decoration-muted/60">{c.before}</span> → <span className="text-ink">{c.after}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {hasRaw && (
            <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2 font-mono text-xs text-ink">
              {JSON.stringify({ action: entry.action, before: entry.old_value, after: entry.new_value }, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

/** Audit log for a company (`platform=false`) or the whole platform. Company readers see sentences, never codes. */
export function AuditTable({ platform = false, companyId }: { platform?: boolean; companyId?: string }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const query = cleanParams({
    page,
    page_size: PAGE_SIZE,
    search,
    category: category || undefined,
    date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
    ...(platform && companyId ? { company: companyId } : {}),
  });
  const logs = platform
    ? $api.useQuery("get", "/api/v1/platform/audit/", { params: { query } })
    : $api.useQuery("get", "/api/v1/audit/", { params: { query } });
  return (
    <Card>
      <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-3">
        <Field label="Search" htmlFor="audit-search">
          <Input id="audit-search" value={search} placeholder="Email address…" onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </Field>
        <Field label="Kind of activity" htmlFor="audit-category">
          <Select id="audit-category" value={category} onChange={(e) => { setCategory(e.target.value as Category | ""); setPage(1); }}>
            <option value="">All activity</option>
            {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </Select>
        </Field>
        <Field label="From date" htmlFor="audit-from">
          <Input id="audit-from" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
        </Field>
      </div>
      <QueryState query={logs} isEmpty={(d) => d.results.length === 0} empty={<EmptyState title="No activity matches" />}>
        {(data) => (
          <>
            <ResponsiveTable
              caption="Audit log"
              rows={data.results}
              rowKey={(e) => e.id}
              columns={[
                { header: "Activity", cell: (e) => (
                    <span className="flex flex-col gap-0.5">
                      <span className="font-semibold text-ink">{e.summary}</span>
                      {e.impersonator_id && <span className="text-xs text-warning">Done by platform support on this person&apos;s behalf</span>}
                      {platform && <span className="font-mono text-xs text-muted">{e.action}</span>}
                    </span>
                  ) },
                { header: "When", cell: (e) => formatDateTime(e.created_at) },
                { header: "IP address", cell: (e) => <span className="font-mono text-xs">{e.ip ?? "—"}</span>, mobileHidden: true },
                { header: "Changes", cell: (e) => <Changes entry={e} raw={platform} /> },
              ]}
            />
            <Pager page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} />
          </>
        )}
      </QueryState>
    </Card>
  );
}
