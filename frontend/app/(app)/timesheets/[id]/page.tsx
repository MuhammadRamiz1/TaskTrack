"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { TimesheetView } from "@/components/common/timesheet-view";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { $api } from "@/lib/api/client";

export default function TimesheetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const sheet = $api.useQuery("get", "/api/v1/time/timesheets/{timesheet_id}/", { params: { path: { timesheet_id: id } } });
  return (
    <>
      <Link href="/timesheets" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-link">
        <ArrowLeft className="size-4" /> Timesheets
      </Link>
      {sheet.data ? <TimesheetView sheet={sheet.data} /> : sheet.isPending ? <LoadingRows /> : <ErrorState error={sheet.error} onRetry={() => sheet.refetch()} />}
    </>
  );
}
