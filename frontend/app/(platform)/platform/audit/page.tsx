"use client";

import { AuditTable } from "@/components/common/audit-table";
import { PageHeader } from "@/components/ui/states";

export default function PlatformAuditPage() {
  return (
    <>
      <PageHeader title="Platform audit log" description="Every change across all companies, including impersonated requests." />
      <AuditTable platform />
    </>
  );
}
