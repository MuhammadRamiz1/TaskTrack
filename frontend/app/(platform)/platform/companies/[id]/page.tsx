"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Eye, PauseCircle, PlayCircle, Trash2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { AuditTable } from "@/components/common/audit-table";
import { Pager, ResponsiveTable } from "@/components/common/pager";
import { COMPANY_TONE, USER_TONE } from "@/components/common/tones";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card, CardHeader, Stat, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingRows, PageHeader, QueryState } from "@/components/ui/states";
import { $api, api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import { useSession } from "@/lib/auth/session";
import { setAccessToken } from "@/lib/auth/token";
import { formatBytes, formatDate, formatDateTime } from "@/lib/utils";

type AdminValues = { email: string; first_name: string; last_name: string; role: "HR" | "COMPANY_ADMIN" };

function InviteAdminDialog({ companyId, onClose }: { companyId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const form = useForm<AdminValues>({ defaultValues: { email: "", first_name: "", last_name: "", role: "HR" } });
  const invite = $api.useMutation("post", "/api/v1/platform/companies/{company_id}/admins/", {
    onSuccess: (u) => {
      toast.success(`Invite sent to ${u.email}`);
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/platform/companies/{company_id}/users/"] });
      onClose();
    },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, ["email", "first_name", "last_name"]),
  });
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Invite first administrator" description="They receive a one-time link to set their password.">
        <form className="grid gap-4 sm:grid-cols-2" noValidate
              onSubmit={form.handleSubmit((body) => invite.mutate({ params: { path: { company_id: companyId } }, body }))}>
          <Field label="Email" htmlFor="email" error={errors.email?.message} required className="sm:col-span-2">
            <Input type="email" {...form.register("email", { required: "Enter an email" })} />
          </Field>
          <Field label="First name" htmlFor="first_name" error={errors.first_name?.message} required>
            <Input {...form.register("first_name", { required: "Required" })} />
          </Field>
          <Field label="Last name" htmlFor="last_name">
            <Input {...form.register("last_name")} />
          </Field>
          <Field label="Role" htmlFor="role" className="sm:col-span-2">
            <Select {...form.register("role")}>
              <option value="HR">HR</option>
              <option value="COMPANY_ADMIN">Company admin</option>
            </Select>
          </Field>
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={invite.isPending}>Send invite</Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Users({ companyId }: { companyId: string }) {
  const router = useRouter();
  const { startSession } = useSession();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState<{ id: string; full_name: string } | null>(null);
  const users = $api.useQuery("get", "/api/v1/platform/companies/{company_id}/users/", {
    params: { path: { company_id: companyId }, query: { page, search: search || undefined } },
  });
  const impersonate = $api.useMutation("post", "/api/v1/platform/impersonations/", {
    onSuccess: async (data) => {
      setAccessToken(data.access);
      const me = (await api.GET("/api/v1/auth/me/")).data!;
      startSession(data.access, me);
      toast.warning(`Viewing as ${me.full_name} (read-only)`);
      router.push("/dashboard");
    },
  });
  return (
    <Card>
      <div className="border-b border-line p-4">
        <Input aria-label="Search users" placeholder="Search by name or email" value={search}
               onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
      </div>
      <QueryState query={users} isEmpty={(d) => !d.results.length} empty={<EmptyState title="No users yet" />}>
        {(data) => (
          <>
            <ResponsiveTable
              caption="Company users"
              rows={data.results}
              rowKey={(u) => u.id}
              columns={[
                { header: "Name", cell: (u) => (
                    <span><span className="font-semibold text-ink">{u.full_name}</span>
                      <span className="block text-xs text-muted">{u.email}</span></span>
                  ) },
                { header: "Roles", cell: (u) => u.roles.join(", ") || "—" },
                { header: "Status", cell: (u) => <Badge tone={USER_TONE[u.status ?? "ACTIVE"]}>{u.status}</Badge> },
                { header: "Last sign-in", cell: (u) => formatDateTime(u.last_login), mobileHidden: true },
                { header: "", cell: (u) => u.status === "ACTIVE" && (
                    <Button variant="outline" size="sm" onClick={() => setTarget(u)}><Eye /> View as</Button>
                  ) },
              ]}
            />
            <Pager page={page} pageSize={25} count={data.count} onPage={setPage} />
          </>
        )}
      </QueryState>
      <ConfirmDialog
        open={Boolean(target)}
        onOpenChange={(o) => !o && setTarget(null)}
        title={`View TaskTrack as ${target?.full_name ?? ""}`}
        description="Read-only for 30 minutes. Every request is recorded in the company's audit log."
        reasonLabel="Reason (e.g. support ticket number)"
        reasonRequired
        confirmLabel="Start impersonation"
        loading={impersonate.isPending}
        onConfirm={(reason) => target && impersonate.mutate({ body: { user_id: target.id, reason } })}
      />
    </Card>
  );
}

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const path = { params: { path: { company_id: id } } };
  const company = $api.useQuery("get", "/api/v1/platform/companies/{company_id}/", path);
  const usage = $api.useQuery("get", "/api/v1/platform/companies/{company_id}/usage/", path);
  const plans = $api.useQuery("get", "/api/v1/platform/plans/");
  const [confirm, setConfirm] = useState<"suspend" | "delete" | "activate" | null>(null);
  const [inviting, setInviting] = useState(false);
  const limits = useForm<{ plan: string; max_users_override: string; max_storage_mb_override: string }>();
  useEffect(() => {
    if (company.data)
      limits.reset({
        plan: company.data.plan.id,
        max_users_override: company.data.max_users_override?.toString() ?? "",
        max_storage_mb_override: company.data.max_storage_mb_override?.toString() ?? "",
      });
  }, [company.data, limits]);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/platform/companies/{company_id}/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/platform/companies/{company_id}/usage/"] });
  };
  const done = (msg: string) => () => { refresh(); setConfirm(null); toast.success(msg); };
  const update = $api.useMutation("patch", "/api/v1/platform/companies/{company_id}/", { onSuccess: done("Company updated") });
  const suspend = $api.useMutation("post", "/api/v1/platform/companies/{company_id}/suspend/", { onSuccess: done("Company suspended") });
  const activate = $api.useMutation("post", "/api/v1/platform/companies/{company_id}/activate/", { onSuccess: done("Company activated") });
  const remove = $api.useMutation("delete", "/api/v1/platform/companies/{company_id}/", { onSuccess: done("Company deleted") });

  if (!company.data) {
    return company.isPending ? <LoadingRows /> : <ErrorState error={company.error} onRetry={() => company.refetch()} />;
  }
  const c = company.data;
  const u = usage.data;
  return (
    <>
      <Link href="/platform/companies" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-link">
        <ArrowLeft className="size-4" /> Companies
      </Link>
      <PageHeader
        title={c.name}
        description={<span className="flex items-center gap-2"><Badge tone={COMPANY_TONE[c.status ?? "ACTIVE"]}>{c.status}</Badge> created {formatDate(c.created_at)}</span>}
        actions={
          <>
            <Button variant="outline" onClick={() => setInviting(true)} disabled={c.status !== "ACTIVE"}><UserPlus /> Invite admin</Button>
            {c.status === "ACTIVE" ? (
              <Button variant="outline" onClick={() => setConfirm("suspend")}><PauseCircle /> Suspend</Button>
            ) : (
              <Button variant="outline" onClick={() => setConfirm("activate")}><PlayCircle /> Activate</Button>
            )}
            {c.status !== "DELETED" && <Button variant="danger" onClick={() => setConfirm("delete")}><Trash2 /> Delete</Button>}
          </>
        }
      />
      {c.status === "SUSPENDED" && (
        <p role="status" className="mb-4 rounded-xl bg-warning-soft px-4 py-3 text-sm text-warning">
          Suspended {formatDateTime(c.suspended_at)}: {c.suspended_reason}
        </p>
      )}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Active users" value={u?.users.active ?? "—"} />
        <Stat label="Pending invites" value={u?.users.invited ?? "—"} />
        <Stat label="Seats" value={u ? `${(u.users.active ?? 0) + (u.users.invited ?? 0)} / ${u.max_users}` : "—"} />
        <Stat label="Storage" value={u ? formatBytes(u.storage_used_bytes) : "—"} hint={u ? `of ${u.max_storage_mb} MB` : undefined} />
      </div>
      <Tabs defaultValue="users">
        <TabsList className="mb-4">
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="plan">Plan & limits</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><Users companyId={id} /></TabsContent>
        <TabsContent value="plan">
          <Card className="max-w-2xl">
            <CardHeader title="Plan & limits" description="Overrides replace the plan's defaults for this company only." />
            <form className="grid gap-4 p-5 sm:grid-cols-3" noValidate
                  onSubmit={limits.handleSubmit((v) => update.mutate({ ...path, body: {
                    plan: v.plan,
                    max_users_override: v.max_users_override === "" ? null : Number(v.max_users_override),
                    max_storage_mb_override: v.max_storage_mb_override === "" ? null : Number(v.max_storage_mb_override),
                  } }))}>
              <Field label="Plan" htmlFor="plan">
                <Select {...limits.register("plan")}>
                  {(plans.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </Field>
              <Field label="Max users override" htmlFor="max_users_override" hint={`Plan: ${c.plan.max_users}`}>
                <Input type="number" min={1} {...limits.register("max_users_override")} />
              </Field>
              <Field label="Storage override (MB)" htmlFor="max_storage_mb_override" hint={`Plan: ${c.plan.max_storage_mb}`}>
                <Input type="number" min={0} {...limits.register("max_storage_mb_override")} />
              </Field>
              <div className="sm:col-span-3"><Button type="submit" loading={update.isPending}>Save limits</Button></div>
            </form>
          </Card>
        </TabsContent>
        <TabsContent value="audit"><AuditTable platform companyId={id} /></TabsContent>
      </Tabs>

      {inviting && <InviteAdminDialog companyId={id} onClose={() => setInviting(false)} />}
      <ConfirmDialog
        open={confirm === "suspend"} onOpenChange={() => setConfirm(null)}
        title={`Suspend ${c.name}?`} description="All users are signed out and cannot sign in until you activate the company."
        reasonLabel="Reason" reasonRequired confirmLabel="Suspend" danger loading={suspend.isPending}
        onConfirm={(reason) => suspend.mutate({ ...path, body: { reason } })}
      />
      <ConfirmDialog
        open={confirm === "activate"} onOpenChange={() => setConfirm(null)}
        title={`Activate ${c.name}?`} confirmLabel="Activate" loading={activate.isPending}
        onConfirm={() => activate.mutate(path)}
      />
      <ConfirmDialog
        open={confirm === "delete"} onOpenChange={() => setConfirm(null)}
        title={`Delete ${c.name}?`} description="The company is disabled and everyone is signed out. Data is kept and the company can be re-activated."
        confirmLabel="Delete company" danger loading={remove.isPending}
        onConfirm={() => remove.mutate(path)}
      />
    </>
  );
}
