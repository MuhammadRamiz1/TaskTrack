"use client";

import { ClipboardCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { PriorityBadge, type TaskPriority } from "@/components/tasks/meta";
import { Card } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { formatDate, timeAgo } from "@/lib/utils";

export default function ReviewsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const queue = $api.useQuery("get", "/api/v1/reviews/queue/", { params: { query: { page } } });
  return (
    <>
      <PageHeader title="Reviews" description="Work submitted to you, oldest first. Approve it or request changes on the task." />
      <Card>
        <QueryState query={queue} isEmpty={(d) => !d.results.length}
                    empty={<EmptyState icon={<ClipboardCheck className="size-6" />} title="Nothing to review" description="Submitted work appears here." />}>
          {(data) => (
            <>
              <ResponsiveTable
                caption="Reviews waiting for you"
                rows={data.results}
                rowKey={(r) => r.id}
                onRowClick={(r) => router.push(`/tasks/${r.task.id}`)}
                columns={[
                  { header: "Task", cell: (r) => (
                      <span className="flex flex-col"><span className="font-mono text-xs text-muted">{r.task.key}</span>
                        <span className="font-semibold text-ink">{r.task.title}</span></span>
                    ) },
                  { header: "Round", cell: (r) => r.round },
                  { header: "Submitted by", cell: (r) => r.submitted_by.full_name },
                  { header: "Waiting", cell: (r) => timeAgo(r.submitted_at) },
                  { header: "Priority", cell: (r) => <PriorityBadge priority={r.task.priority as TaskPriority} />, mobileHidden: true },
                  { header: "Due", cell: (r) => formatDate(r.task.due_date), mobileHidden: true },
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
