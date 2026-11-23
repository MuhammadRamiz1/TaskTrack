"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { TimesheetView } from "@/components/common/timesheet-view";
import { TIMESHEET_TONE } from "@/components/common/tones";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { ErrorState, LoadingRows, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { useMe } from "@/lib/auth/session";
import { formatDate, formatDuration, titleCase } from "@/lib/utils";

export default function TimesheetsPage() {
  const me = useMe();
  const router = useRouter();
  const [page, setPage] = useState(1);
  const current = $api.useQuery("get", "/api/v1/time/timesheets/current/");
  const history = $api.useQuery("get", "/api/v1/time/timesheets/", { params: { query: { user: me.id, page } } });
  return (
    <>
      <PageHeader title="Timesheets" description="Your logged time by week. Submit each week for approval." />
      <div className="flex flex-col gap-5">
        {current.data ? <TimesheetView sheet={current.data} /> : current.isPending ? <LoadingRows /> : <ErrorState error={current.error} />}
        <Card>
          <CardHeader title="Previous weeks" />
          <QueryState query={history} isEmpty={(d) => !d.results.length} empty={<p className="px-5 py-6 text-sm text-muted">No timesheets yet.</p>}>
            {(data) => (
              <>
                <ResponsiveTable
                  caption="Timesheet history"
                  rows={data.results}
                  rowKey={(s) => s.id}
                  onRowClick={(s) => router.push(`/timesheets/${s.id}`)}
                  columns={[
                    { header: "Week", cell: (s) => <span className="font-semibold text-ink">{formatDate(s.period_start)} – {formatDate(s.period_end)}</span> },
                    { header: "Logged", cell: (s) => formatDuration(s.total_seconds) },
                    { header: "Status", cell: (s) => <Badge tone={TIMESHEET_TONE[s.status ?? "OPEN"]}>{titleCase(s.status ?? "")}</Badge> },
                  ]}
                />
                <Pager page={page} pageSize={25} count={data.count} onPage={setPage} />
              </>
            )}
          </QueryState>
        </Card>
      </div>
    </>
  );
}
