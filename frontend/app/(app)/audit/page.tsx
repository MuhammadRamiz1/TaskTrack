"use client";

import { AuditTable } from "@/components/common/audit-table";
import { PageHeader } from "@/components/ui/states";

export default function AuditPage() {
  return (
    <>
      <PageHeader title="Audit log" description="Who changed what, and when. Entries cannot be edited or deleted." />
      <AuditTable />
    </>
  );
}
