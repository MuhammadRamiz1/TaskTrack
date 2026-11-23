"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Lock, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card, CardHeader, Checkbox, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/states";
import { STATUS_META } from "@/components/tasks/meta";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useSession } from "@/lib/auth/session";
import { cn, titleCase } from "@/lib/utils";

type Settings = components["schemas"]["CompanySettings"];
type Role = components["schemas"]["RoleOutput"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const TIMEZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"];
type Scope = "COMPANY" | "TEAM" | "PROJECT" | "OWN";

function CompanySettingsForm() {
  const qc = useQueryClient();
  const settings = $api.useQuery("get", "/api/v1/company/settings/");
  const form = useForm<Settings>();
  useEffect(() => {
    if (settings.data) form.reset(settings.data);
  }, [settings.data, form]);
  const save = $api.useMutation("patch", "/api/v1/company/settings/", {
    onSuccess: (data) => {
      qc.setQueryData(["get", "/api/v1/company/settings/"], data);
      form.reset(data);
      toast.success("Company settings saved");
    },
    onError: (e) => applyFieldErrors(e, form.setError, ["name", "invite_expiry_hours", "working_days", "timezone"]),
  });
  const days = form.watch("working_days") as number[] | undefined;
  const toggles: [keyof Settings, string, string][] = [
    ["enforce_2fa", "Require two-factor authentication", "Everyone must set up an authenticator app."],
    ["require_assignment_ack", "Require assignment acknowledgement", "Assignees confirm they have seen new work."],
    ["timer_start_moves_to_in_progress", "Starting a timer starts the task", "ASSIGNED tasks move to IN_PROGRESS on timer start."],
    ["enforce_dependencies", "Enforce dependencies", "Tasks cannot start while they wait on unfinished tasks."],
    ["allow_self_review", "Allow self-review", "Company-wide reviewers may approve work they are assigned to."],
  ];
  return (
    <QueryState query={settings}>
      {() => (
        <form
          className="grid gap-5 p-5"
          noValidate
          onSubmit={form.handleSubmit((values) => {
            // id, slug and status are read-only on this endpoint: send only editable fields.
            const editable = Object.fromEntries(
              Object.entries(values).filter(([key]) => !["id", "slug", "status"].includes(key)),
            ) as Partial<Settings>;
            save.mutate({ body: editable });
          })}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Company name" htmlFor="name" error={form.formState.errors.name?.message}>
              <Input {...form.register("name")} />
            </Field>
            <Field label="Time zone" htmlFor="tz">
              <Select {...form.register("timezone")}>
                {TIMEZONES.map((tz) => <option key={tz}>{tz}</option>)}
              </Select>
            </Field>
            <Field label="Invite links expire after (hours)" htmlFor="invite_expiry_hours"
                   error={form.formState.errors.invite_expiry_hours?.message}>
              <Input type="number" min={1} max={720} {...form.register("invite_expiry_hours", { valueAsNumber: true })} />
            </Field>
            <Field label="Working day (minutes)" htmlFor="daily_working_minutes">
              <Input type="number" min={60} max={1440} {...form.register("daily_working_minutes", { valueAsNumber: true })} />
            </Field>
            <Field label="Week starts on" htmlFor="week_start">
              <Select {...form.register("week_start", { valueAsNumber: true })}>
                {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
              </Select>
            </Field>
            <Field label="Stop timers after (hours)" htmlFor="max_timer_hours">
              <Input type="number" min={1} max={24} {...form.register("max_timer_hours", { valueAsNumber: true })} />
            </Field>
          </div>
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-ink">Working days</legend>
            <div className="flex flex-wrap gap-2">
              {WEEKDAYS.map((d, i) => {
                const on = days?.includes(i);
                return (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      form.setValue("working_days", (on ? days!.filter((x) => x !== i) : [...(days ?? []), i]).sort(), { shouldDirty: true })
                    }
                    className={cn("h-10 min-w-12 rounded-xl border px-3 text-sm font-semibold",
                      on ? "border-primary-600 bg-primary-600 text-on-primary" : "border-line bg-surface text-muted")}
                  >
                    {d}
                  </button>
                );
              })}
            </div>
          </fieldset>
          <div className="divide-y divide-line rounded-xl border border-line">
            {toggles.map(([key, label, hint]) => (
              <label key={key} className="flex cursor-pointer items-center justify-between gap-4 px-4 py-3">
                <span>
                  <span className="block text-sm font-semibold text-ink">{label}</span>
                  <span className="block text-xs text-muted">{hint}</span>
                </span>
                <Switch
                  checked={Boolean(form.watch(key))}
                  onCheckedChange={(v) => form.setValue(key, v as never, { shouldDirty: true })}
                />
              </label>
            ))}
          </div>
          <div><Button type="submit" loading={save.isPending} disabled={!form.formState.isDirty}>Save settings</Button></div>
        </form>
      )}
    </QueryState>
  );
}

function RoleEditor({ role, onClose }: { role: Role | "new"; onClose: () => void }) {
  const qc = useQueryClient();
  const catalogue = $api.useQuery("get", "/api/v1/company/permissions/");
  const initial = role === "new" ? [] : (role.permissions as { code: string; scope: string }[]);
  const [grants, setGrants] = useState<Record<string, string>>(() => Object.fromEntries(initial.map((g) => [g.code, g.scope])));
  const [name, setName] = useState(role === "new" ? "" : role.name);
  const [rank, setRank] = useState(role === "new" ? 20 : role.rank);
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/company/roles/"] });
    toast.success("Role saved");
    onClose();
  };
  const create = $api.useMutation("post", "/api/v1/company/roles/", { onSuccess: done });
  const setPerms = $api.useMutation("put", "/api/v1/company/roles/{role_id}/permissions/", { onSuccess: done });
  const modules = useMemo(() => {
    const map = new Map<string, components["schemas"]["PermissionOutput"][]>();
    for (const p of catalogue.data ?? []) map.set(p.module, [...(map.get(p.module) ?? []), p]);
    return [...map.entries()];
  }, [catalogue.data]);
  const permissions = Object.entries(grants).map(([code, scope]) => ({ code, scope: scope as Scope }));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={role === "new" ? "New role" : `Edit ${role.name}`}
                     description="Grant permissions and the widest scope each one reaches.">
        {role === "new" && (
          <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_120px]">
            <Field label="Name" htmlFor="role-name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Rank" htmlFor="role-rank" hint="Below your own">
              <Input type="number" min={1} max={89} value={rank} onChange={(e) => setRank(Number(e.target.value))} />
            </Field>
          </div>
        )}
        <QueryState query={catalogue}>
          {() => (
            <div className="flex flex-col gap-4">
              {modules.map(([module, perms]) => (
                <fieldset key={module} className="rounded-xl border border-line">
                  <legend className="ml-3 px-1 text-xs font-bold uppercase tracking-wide text-muted">{module}</legend>
                  <ul className="divide-y divide-line">
                    {perms.map((p) => {
                      const on = p.code in grants;
                      return (
                        <li key={p.code} className="flex flex-wrap items-center gap-3 px-3 py-2">
                          <Checkbox
                            id={`perm-${p.code}`}
                            checked={on}
                            onCheckedChange={(v) =>
                              setGrants((g) => {
                                const next = { ...g };
                                if (v) next[p.code] = (p.allowed_scopes as string[])[0];
                                else delete next[p.code];
                                return next;
                              })
                            }
                          />
                          <label htmlFor={`perm-${p.code}`} className="min-w-0 flex-1 text-sm">
                            <span className="font-semibold text-ink">{p.description}</span>
                            <span className="block font-mono text-xs text-muted">{p.code}</span>
                          </label>
                          {on && (
                            <Select className="h-9 w-32 text-sm" aria-label={`Scope for ${p.code}`} value={grants[p.code]}
                                    onChange={(e) => setGrants((g) => ({ ...g, [p.code]: e.target.value }))}>
                              {(p.allowed_scopes as string[]).map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
                            </Select>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </fieldset>
              ))}
            </div>
          )}
        </QueryState>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            loading={create.isPending || setPerms.isPending}
            disabled={role === "new" && !name.trim()}
            onClick={() =>
              role === "new"
                ? create.mutate({ body: { name, rank, description: "", permissions } })
                : setPerms.mutate({ params: { path: { role_id: role.id } }, body: { permissions } })
            }
          >
            Save role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Roles() {
  const roles = $api.useQuery("get", "/api/v1/company/roles/");
  const [editing, setEditing] = useState<Role | "new" | null>(null);
  return (
    <>
      <div className="flex justify-end border-b border-line p-4">
        <Button size="sm" onClick={() => setEditing("new")}><Plus /> New role</Button>
      </div>
      <QueryState query={roles}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">{r.name} {r.is_system && <Badge className="ml-1">System</Badge>}</p>
                  <p className="text-xs text-muted">Rank {r.rank} · {r.permissions.length} permissions · {r.holders ?? 0} people</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setEditing(r)}>Permissions</Button>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {editing && <RoleEditor role={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function WorkflowRules() {
  const qc = useQueryClient();
  const rules = $api.useQuery("get", "/api/v1/company/workflow/rules/");
  const roles = $api.useQuery("get", "/api/v1/company/roles/");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["get", "/api/v1/company/workflow/rules/"] });
  const update = $api.useMutation("patch", "/api/v1/company/workflow/rules/{rule_id}/", { onSuccess: refresh });
  const reset = $api.useMutation("post", "/api/v1/company/workflow/rules/reset/", {
    onSuccess: () => { refresh(); toast.success("Default rules restored"); },
  });
  const roleKeys = (roles.data ?? []).map((r) => r.key);
  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-line p-4">
        <p className="text-sm text-muted">Which roles may move a task between statuses. Locked rules protect the review process.</p>
        <Button variant="outline" size="sm" loading={reset.isPending} onClick={() => reset.mutate({})}>Restore defaults</Button>
      </div>
      <QueryState query={rules}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.filter((r) => r.trigger !== "SYSTEM").map((r) => (
              <li key={r.id} className={cn("flex flex-col gap-2 px-5 py-3 lg:flex-row lg:items-center", !r.is_active && "opacity-60")}>
                <div className="flex min-w-64 items-center gap-2 text-sm font-semibold text-ink">
                  {STATUS_META[r.from_status].label} → {STATUS_META[r.to_status].label}
                  {r.trigger && r.trigger !== "MANUAL" && <Badge tone="info">{titleCase(r.trigger)}</Badge>}
                  {r.is_locked && <Lock className="size-3.5 text-muted" aria-label="Core rule" />}
                </div>
                <div className="flex flex-1 flex-wrap gap-1.5">
                  {roleKeys.map((key) => {
                    const on = (r.allowed_roles as string[]).includes(key);
                    return (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={on}
                        disabled={update.isPending}
                        onClick={() =>
                          update.mutate({
                            params: { path: { rule_id: r.id } },
                            body: { allowed_roles: on ? (r.allowed_roles as string[]).filter((k) => k !== key) : [...(r.allowed_roles as string[]), key] },
                          })
                        }
                        className={cn("rounded-full border px-2.5 py-1 text-xs font-semibold",
                          on ? "border-primary-300 bg-primary-100 text-primary-700" : "border-line text-muted")}
                      >
                        {titleCase(key)}
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center gap-4 text-xs text-muted">
                  <label className="flex items-center gap-2">
                    Comment
                    <Switch checked={r.requires_comment} disabled={r.is_locked}
                            onCheckedChange={(v) => update.mutate({ params: { path: { rule_id: r.id } }, body: { requires_comment: v } })} />
                  </label>
                  <label className="flex items-center gap-2">
                    Active
                    <Switch checked={r.is_active} disabled={r.is_locked}
                            onCheckedChange={(v) => update.mutate({ params: { path: { rule_id: r.id } }, body: { is_active: v } })} />
                  </label>
                </div>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </>
  );
}

export default function CompanySettingsPage() {
  const { can } = useSession();
  const tabs = [
    can("company.settings.manage") && { value: "general", label: "General", body: <CompanySettingsForm /> },
    can("role.manage") && { value: "roles", label: "Roles & permissions", body: <Roles /> },
    can("workflow.manage") && { value: "workflow", label: "Workflow", body: <WorkflowRules /> },
  ].filter(Boolean) as { value: string; label: string; body: React.ReactNode }[];
  if (!tabs.length) return null;
  return (
    <Tabs defaultValue={tabs[0].value}>
      <TabsList className="mb-4">
        {tabs.map((t) => <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>)}
      </TabsList>
      {tabs.map((t) => (
        <TabsContent key={t.value} value={t.value}>
          <Card>
            <CardHeader title={t.label} />
            {t.body}
          </Card>
        </TabsContent>
      ))}
    </Tabs>
  );
}
