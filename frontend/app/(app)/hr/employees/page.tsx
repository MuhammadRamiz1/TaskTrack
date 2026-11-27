"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Search, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Pager, ResponsiveTable } from "@/components/common/pager";
import { INVITE_TONE, USER_TONE } from "@/components/common/tones";
import { EmployeeImportDialog } from "@/components/hr/employee-import-dialog";
import { Can } from "@/components/layout/guards";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Avatar, Badge, Card, Checkbox } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import { cleanParams, titleCase } from "@/lib/utils";

const PAGE_SIZE = 20;
type Values = { email: string; first_name: string; last_name: string; job_title: string; role_id: string; send_invite: boolean };

function NewEmployeeDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const roles = $api.useQuery("get", "/api/v1/hr/roles/");
  const form = useForm<Values>({
    defaultValues: { email: "", first_name: "", last_name: "", job_title: "", role_id: "", send_invite: true },
  });
  const create = $api.useMutation("post", "/api/v1/hr/employees/", {
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/"] });
      toast.success(form.getValues("send_invite") ? `Invite sent to ${e.email}` : `${e.full_name} added`);
      router.push(`/hr/employees/${e.id}`);
    },
    onError: (err: unknown) => applyFieldErrors(err, form.setError, ["email", "first_name", "last_name", "job_title"]),
  });
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Add employee" description="The account stays INVITED until they set a password from the invite link.">
        <form className="grid gap-4 sm:grid-cols-2" noValidate
              onSubmit={form.handleSubmit(({ role_id, ...v }) => create.mutate({ body: { ...v, role_ids: role_id ? [role_id] : [] } }))}>
          <Field label="Work email" htmlFor="email" error={errors.email?.message} required className="sm:col-span-2">
            <Input type="email" autoComplete="off" {...form.register("email", { required: "Enter an email" })} />
          </Field>
          <Field label="First name" htmlFor="first_name" error={errors.first_name?.message} required>
            <Input {...form.register("first_name", { required: "Required" })} />
          </Field>
          <Field label="Last name" htmlFor="last_name" error={errors.last_name?.message}>
            <Input {...form.register("last_name")} />
          </Field>
          <Field label="Job title" htmlFor="job_title">
            <Input {...form.register("job_title")} />
          </Field>
          <Field label="Role" htmlFor="role_id" hint="Defaults to Team Member">
            <Select {...form.register("role_id")}>
              <option value="">Team Member</option>
              {(roles.data ?? []).filter((r) => r.key !== "TEAM_MEMBER").map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </Select>
          </Field>
          <label className="flex items-center gap-3 text-sm font-semibold text-ink sm:col-span-2">
            <Checkbox checked={form.watch("send_invite")} onCheckedChange={(v) => form.setValue("send_invite", v === true)} />
            Email the invite link now
          </label>
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={create.isPending}>Add employee</Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function EmployeesPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [role, setRole] = useState("");
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const roles = $api.useQuery("get", "/api/v1/hr/roles/");
  const employees = $api.useQuery("get", "/api/v1/hr/employees/", {
    params: {
      query: cleanParams({
        page, page_size: PAGE_SIZE, search, role,
        status: status ? [status as "ACTIVE"] : undefined,
      }),
    },
  });
  return (
    <>
      <PageHeader title="People" description="Employee accounts, invites and access."
                  actions={
                    <Can anyOf={["employee.create"]}>
                      <div className="flex gap-2">
                        <Button variant="outline" onClick={() => setImporting(true)}><FileSpreadsheet /> Import from sheet</Button>
                        <Button onClick={() => setCreating(true)}><UserPlus /> Add employee</Button>
                      </div>
                    </Can>
                  } />
      <Card>
        <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-[1fr_180px_180px]">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-placeholder" />
            <Input aria-label="Search people" placeholder="Name, email or title" className="pl-9" value={search}
                   onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="INVITED">Invited</option>
            <option value="DEACTIVATED">Deactivated</option>
          </Select>
          <Select aria-label="Role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
            <option value="">All roles</option>
            {(roles.data ?? []).map((r) => <option key={r.id} value={r.key}>{r.name}</option>)}
          </Select>
        </div>
        <QueryState query={employees} isEmpty={(d) => !d.results.length} empty={<EmptyState title="No people match" />}>
          {(data) => (
            <>
              <ResponsiveTable
                caption="Employees"
                rows={data.results}
                rowKey={(e) => e.id}
                onRowClick={(e) => router.push(`/hr/employees/${e.id}`)}
                columns={[
                  { header: "Name", cell: (e) => (
                      <span className="flex items-center gap-3">
                        <Avatar name={e.full_name} />
                        <span className="min-w-0">
                          <span className="block truncate font-semibold text-ink">{e.full_name}</span>
                          <span className="block truncate text-xs text-muted">{e.email}</span>
                        </span>
                      </span>
                    ) },
                  { header: "Role", cell: (e) => e.roles.map((r) => r.name).join(", ") },
                  { header: "Status", cell: (e) => <Badge tone={USER_TONE[e.status ?? "ACTIVE"]}>{titleCase(e.status ?? "")}</Badge> },
                  { header: "Invite", mobileHidden: true, cell: (e) => {
                      return e.status === "INVITED" ? <Badge tone={INVITE_TONE[e.invite.state]}>{titleCase(e.invite.state)}</Badge> : <span className="text-muted">—</span>;
                    } },
                  { header: "Manager", mobileHidden: true, cell: (e) => e.manager?.full_name ?? "—" },
                ]}
              />
              <Pager page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} />
            </>
          )}
        </QueryState>
      </Card>
      {creating && <NewEmployeeDialog onClose={() => setCreating(false)} />}
      {importing && <EmployeeImportDialog onClose={() => setImporting(false)} />}
    </>
  );
}
