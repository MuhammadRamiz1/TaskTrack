"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { Field, Input } from "@/components/ui/form";
import { Card } from "@/components/ui/primitives";
import { EmptyState, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cleanParams, formatDateTime } from "@/lib/utils";

type Entry = components["schemas"]["AuditLogOutput"];
const PAGE_SIZE = 25;

function Changes({ entry }: { entry: Entry }) {
  const [open, setOpen] = useState(false);
  if (!entry.old_value && !entry.new_value) return <span className="text-muted">—</span>;
  return (
    <div>
      <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold text-link" onClick={() => setOpen((o) => !o)}
              aria-expanded={open}>
        Details <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <pre className="mt-2 max-w-[520px] overflow-x-auto rounded-lg bg-surface-2 p-2 text-left font-mono text-xs text-ink">
          {JSON.stringify({ before: entry.old_value, after: entry.new_value }, null, 2)}
        </pre>
      )}
    </div>
  );
}

/** Audit log for a company (`platform=false`) or the whole platform. */
export function AuditTable({ platform = false, companyId }: { platform?: boolean; companyId?: string }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const query = cleanParams({
    page,
    page_size: PAGE_SIZE,
    search,
    action,
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
          <Input value={search} placeholder="Action, email, entity…" onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        </Field>
        <Field label="Action starts with" htmlFor="audit-action">
          <Input value={action} placeholder="e.g. task., employee." onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        </Field>
        <Field label="From date" htmlFor="audit-from">
          <Input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
        </Field>
      </div>
      <QueryState query={logs} isEmpty={(d) => d.results.length === 0} empty={<EmptyState title="No audit entries match" />}>
        {(data) => (
          <>
            <ResponsiveTable
              caption="Audit log"
              rows={data.results}
              rowKey={(e) => e.id}
              columns={[
                { header: "Action", cell: (e) => <span className="font-mono text-[13px] font-semibold">{e.action}</span> },
                { header: "When", cell: (e) => formatDateTime(e.created_at) },
                { header: "Actor", cell: (e) => (
                    <span>{e.actor_email || "System"}{e.impersonator_id && <span className="ml-1 text-xs text-warning">(impersonated)</span>}</span>
                  ) },
                { header: "Entity", cell: (e) => <span className="text-muted">{e.entity_type}</span>, mobileHidden: true },
                { header: "IP", cell: (e) => <span className="font-mono text-xs">{e.ip ?? "—"}</span>, mobileHidden: true },
                { header: "Changes", cell: (e) => <Changes entry={e} /> },
              ]}
            />
            <Pager page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} />
          </>
        )}
      </QueryState>
    </Card>
  );
}
