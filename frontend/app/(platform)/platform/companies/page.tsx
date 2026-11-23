"use client";

import { Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { COMPANY_TONE } from "@/components/common/tones";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import { cleanParams, formatDate } from "@/lib/utils";

const PAGE_SIZE = 20;

function NewCompanyDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const plans = $api.useQuery("get", "/api/v1/platform/plans/");
  const form = useForm<{ name: string; plan: string; timezone: string }>({
    defaultValues: { name: "", plan: "", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
  });
  const create = $api.useMutation("post", "/api/v1/platform/companies/", {
    onSuccess: (c) => {
      toast.success(`${c.name} created`);
      router.push(`/platform/companies/${c.id}`);
    },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, ["name", "plan", "timezone"]),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="New company" description="Roles and default workflow rules are created automatically.">
        <form className="flex flex-col gap-4" noValidate
              onSubmit={form.handleSubmit((body) => create.mutate({ body }))}>
          <Field label="Company name" htmlFor="name" error={form.formState.errors.name?.message} required>
            <Input {...form.register("name", { required: "Enter a name" })} />
          </Field>
          <Field label="Plan" htmlFor="plan" error={form.formState.errors.plan?.message} required>
            <Select {...form.register("plan", { required: "Choose a plan" })}>
              <option value="">Choose…</option>
              {(plans.data ?? []).filter((p) => p.is_active).map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.max_users} users)</option>
              ))}
            </Select>
          </Field>
          <Field label="Time zone" htmlFor="timezone">
            <Input {...form.register("timezone")} />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={create.isPending}>Create company</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function CompaniesPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const companies = $api.useQuery("get", "/api/v1/platform/companies/", {
    params: { query: cleanParams({ page, page_size: PAGE_SIZE, search, status: status ? [status as "ACTIVE"] : undefined }) },
  });
  return (
    <>
      <PageHeader title="Companies" description="Tenants on the platform."
                  actions={<Button onClick={() => setCreating(true)}><Plus /> New company</Button>} />
      <Card>
        <div className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-placeholder" />
            <Input aria-label="Search companies" placeholder="Search by name" className="pl-9" value={search}
                   onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Filter by status" className="sm:w-48" value={status}
                  onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="SUSPENDED">Suspended</option>
            <option value="DELETED">Deleted</option>
          </Select>
        </div>
        <QueryState query={companies} isEmpty={(d) => !d.results.length}
                    empty={<EmptyState title="No companies yet" action={<Button onClick={() => setCreating(true)}>Create the first one</Button>} />}>
          {(data) => (
            <>
              <ResponsiveTable
                caption="Companies"
                rows={data.results}
                rowKey={(c) => c.id}
                onRowClick={(c) => router.push(`/platform/companies/${c.id}`)}
                columns={[
                  { header: "Company", cell: (c) => <span className="font-semibold text-ink">{c.name}</span> },
                  { header: "Status", cell: (c) => <Badge tone={COMPANY_TONE[c.status ?? "ACTIVE"]}>{c.status}</Badge> },
                  { header: "Plan", cell: (c) => c.plan.name },
                  { header: "Users", cell: (c) => `${c.user_count ?? 0} / ${c.max_users}` },
                  { header: "Created", cell: (c) => formatDate(c.created_at), mobileHidden: true },
                ]}
              />
              <Pager page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} />
            </>
          )}
        </QueryState>
      </Card>
      {creating && <NewCompanyDialog onClose={() => setCreating(false)} />}
    </>
  );
}
