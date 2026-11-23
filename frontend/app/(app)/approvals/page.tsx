"use client";

import { Stamp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { Card } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { formatDate, formatDuration, timeAgo } from "@/lib/utils";

export default function ApprovalsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const queue = $api.useQuery("get", "/api/v1/time/approvals/queue/", { params: { query: { page } } });
  return (
    <>
      <PageHeader title="Timesheet approvals" description="Submitted weeks from people you approve for. Separate from task reviews." />
      <Card>
        <QueryState query={queue} isEmpty={(d) => !d.results.length}
                    empty={<EmptyState icon={<Stamp className="size-6" />} title="No timesheets waiting" />}>
          {(data) => (
            <>
              <ResponsiveTable
                caption="Timesheets waiting for approval"
                rows={data.results}
                rowKey={(s) => s.id}
                onRowClick={(s) => router.push(`/timesheets/${s.id}`)}
                columns={[
                  { header: "Person", cell: (s) => <span className="font-semibold text-ink">{s.user.full_name}</span> },
                  { header: "Week", cell: (s) => `${formatDate(s.period_start)} – ${formatDate(s.period_end)}` },
                  { header: "Logged", cell: (s) => formatDuration(s.total_seconds) },
                  { header: "Submitted", cell: (s) => timeAgo(s.submitted_at) },
                ]}
              />
              <Pager page={page} pageSize={25} count={data.count} onPage={setPage} />
            </>
          )}
        </QueryState>
      </Card>
    </>
  );
}
