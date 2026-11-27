"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card, Switch } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type Plan = components["schemas"]["Plan"];
type Values = { code: string; name: string; max_users: number; max_storage_mb: number; is_active: boolean;
  reports_pdf: boolean; scheduled_reports: boolean };

function PlanDialog({ plan, onClose }: { plan: Plan | "new"; onClose: () => void }) {
  const qc = useQueryClient();
  const features = (plan !== "new" ? plan.features : {}) as Record<string, boolean>;
  const form = useForm<Values>({
    defaultValues: plan === "new"
      ? { code: "", name: "", max_users: 25, max_storage_mb: 5120, is_active: true, reports_pdf: true, scheduled_reports: true }
      : { ...plan, reports_pdf: Boolean(features.reports_pdf), scheduled_reports: Boolean(features.scheduled_reports) },
  });
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/platform/plans/"] });
    toast.success("Plan saved");
    onClose();
  };
  const fields = ["code", "name", "max_users", "max_storage_mb"] as const;
  const create = $api.useMutation("post", "/api/v1/platform/plans/", { onSuccess: done,
    onError: (e: unknown) => applyFieldErrors(e, form.setError, fields) });
  const update = $api.useMutation("patch", "/api/v1/platform/plans/{plan_id}/", { onSuccess: done,
    onError: (e: unknown) => applyFieldErrors(e, form.setError, fields) });
  const submit = form.handleSubmit(({ reports_pdf, scheduled_reports, ...v }) => {
    const body = { ...v, features: { reports_pdf, scheduled_reports } };
    if (plan === "new") create.mutate({ body });
    else update.mutate({ params: { path: { plan_id: plan.id } }, body });
  });
  const { errors } = form.formState;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={plan === "new" ? "New plan" : `Edit ${plan.name}`}>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
          <Field label="Code" htmlFor="code" error={errors.code?.message}>
            <Input disabled={plan !== "new"} {...form.register("code", { required: "Required" })} />
          </Field>
          <Field label="Name" htmlFor="name" error={errors.name?.message}>
            <Input {...form.register("name", { required: "Required" })} />
          </Field>
          <Field label="Max users" htmlFor="max_users" error={errors.max_users?.message}>
            <Input type="number" min={1} {...form.register("max_users", { valueAsNumber: true })} />
          </Field>
          <Field label="Storage (MB)" htmlFor="max_storage_mb" error={errors.max_storage_mb?.message}>
            <Input type="number" min={0} {...form.register("max_storage_mb", { valueAsNumber: true })} />
          </Field>
          {(["reports_pdf", "scheduled_reports", "is_active"] as const).map((key) => (
            <label key={key} className="flex items-center justify-between gap-3 rounded-xl border border-line px-3 py-2.5 text-sm font-semibold text-ink sm:col-span-2">
              {{ reports_pdf: "PDF report export", scheduled_reports: "Scheduled reports", is_active: "Available for new companies" }[key]}
              <Switch checked={form.watch(key)} onCheckedChange={(v) => form.setValue(key, v)} />
            </label>
          ))}
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={create.isPending || update.isPending}>Save plan</Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function PlansPage() {
  const plans = $api.useQuery("get", "/api/v1/platform/plans/");
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  return (
    <>
      <PageHeader title="Plans" description="Default limits and features for companies."
                  actions={<Button onClick={() => setEditing("new")}><Plus /> New plan</Button>} />
      <QueryState query={plans} isEmpty={(d) => !d.length} empty={<EmptyState title="No plans yet" />}>
        {(items) => (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((p) => {
              const f = p.features as Record<string, boolean>;
              return (
                <Card key={p.id} className="flex flex-col gap-3 p-5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-lg font-extrabold text-ink">{p.name}</p>
                      <p className="font-mono text-xs text-muted">{p.code}</p>
                    </div>
                    {!p.is_active && <Badge>Retired</Badge>}
                  </div>
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    <dt className="text-muted">Users</dt><dd className="text-right font-semibold">{p.max_users}</dd>
                    <dt className="text-muted">Storage</dt><dd className="text-right font-semibold">{((p.max_storage_mb ?? 0) / 1024).toFixed(1)} GB</dd>
                  </dl>
                  <div className="flex flex-wrap gap-1.5">
                    {f.reports_pdf && <Badge tone="primary">PDF exports</Badge>}
                    {f.scheduled_reports && <Badge tone="primary">Scheduled reports</Badge>}
                  </div>
                  <Button variant="outline" size="sm" className="mt-auto self-start" onClick={() => setEditing(p)}>
                    <Pencil /> Edit
                  </Button>
                </Card>
              );
            })}
          </div>
        )}
      </QueryState>
      {editing && <PlanDialog plan={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
