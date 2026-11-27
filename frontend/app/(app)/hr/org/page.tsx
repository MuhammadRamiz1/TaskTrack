"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Archive, CalendarOff, FolderKanban, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Avatar, Badge, Card, CardHeader, Checkbox, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useSession } from "@/lib/auth/session";
import { formatDate, titleCase } from "@/lib/utils";

type Team = components["schemas"]["TeamOutput"];
type Project = components["schemas"]["ProjectOutput"];

function useInvalidate(...paths: string[]) {
  const qc = useQueryClient();
  return () => paths.forEach((p) => void qc.invalidateQueries({ queryKey: ["get", p] }));
}

function TeamDialog({ team, onClose }: { team: Team | "new"; onClose: () => void }) {
  const refresh = useInvalidate("/api/v1/org/teams/", "/api/v1/org/teams/{team_id}/members/");
  const isNew = team === "new";
  const form = useForm<{ name: string; description: string }>({
    defaultValues: isNew ? { name: "", description: "" } : { name: team.name, description: team.description ?? "" },
  });
  const [lead, setLead] = useState<Person[]>(!isNew && team.lead ? [team.lead] : []);
  const [add, setAdd] = useState<Person[]>([]);
  const members = $api.useQuery("get", "/api/v1/org/teams/{team_id}/members/",
    { params: { path: { team_id: isNew ? "" : team.id } } }, { enabled: !isNew });
  const create = $api.useMutation("post", "/api/v1/org/teams/", {
    onSuccess: () => { refresh(); toast.success("Team created"); onClose(); },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, ["name"]),
  });
  const update = $api.useMutation("patch", "/api/v1/org/teams/{team_id}/", {
    onSuccess: () => { refresh(); toast.success("Team saved"); },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, ["name"]),
  });
  const setLeadM = $api.useMutation("post", "/api/v1/org/teams/{team_id}/lead/", { onSuccess: () => { refresh(); toast.success("Lead updated"); } });
  const addMembers = $api.useMutation("post", "/api/v1/org/teams/{team_id}/members/", { onSuccess: () => { refresh(); setAdd([]); } });
  const removeMember = $api.useMutation("delete", "/api/v1/org/teams/{team_id}/members/{user_id}/", { onSuccess: refresh });
  const memberIds = (members.data ?? []).map((m) => m.user.id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={isNew ? "New team" : team.name}>
        <form className="grid gap-4" noValidate onSubmit={form.handleSubmit((body) =>
          isNew ? create.mutate({ body }) : update.mutate({ params: { path: { team_id: team.id } }, body }))}>
          <Field label="Name" htmlFor="team-name" error={form.formState.errors.name?.message} required>
            <Input {...form.register("name", { required: "Enter a name" })} />
          </Field>
          <Field label="Description" htmlFor="team-desc">
            <Textarea {...form.register("description")} />
          </Field>
          <div><Button type="submit" loading={create.isPending || update.isPending}>{isNew ? "Create team" : "Save"}</Button></div>
        </form>
        {!isNew && (
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <section>
              <h3 className="mb-2 text-sm font-bold text-ink">Team lead</h3>
              <PeoplePicker single label="Lead" value={lead} onChange={setLead} />
              <Button size="sm" className="mt-2" disabled={!lead[0] || lead[0].id === team.lead?.id} loading={setLeadM.isPending}
                      onClick={() => setLeadM.mutate({ params: { path: { team_id: team.id } }, body: { user_id: lead[0].id } })}>
                Set as lead
              </Button>
            </section>
            <section>
              <h3 className="mb-2 text-sm font-bold text-ink">Members ({memberIds.length})</h3>
              <ul className="mb-3 max-h-48 divide-y divide-line overflow-y-auto rounded-xl border border-line">
                {(members.data ?? []).map((m) => (
                  <li key={m.user.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                    <Avatar name={m.user.full_name} className="size-7" />
                    <span className="min-w-0 flex-1 truncate font-semibold">{m.user.full_name}</span>
                    {team.lead?.id === m.user.id && <Badge tone="primary">Lead</Badge>}
                    <Button variant="ghost" size="sm" aria-label={`Remove ${m.user.full_name}`}
                            onClick={() => removeMember.mutate({ params: { path: { team_id: team.id, user_id: m.user.id } } })}>
                      <Trash2 />
                    </Button>
                  </li>
                ))}
              </ul>
              <PeoplePicker label="Members to add" value={add} onChange={setAdd} exclude={memberIds} />
              <Button size="sm" className="mt-2" disabled={!add.length} loading={addMembers.isPending}
                      onClick={() => addMembers.mutate({ params: { path: { team_id: team.id } }, body: { user_ids: add.map((p) => p.id) } })}>
                <Plus /> Add {add.length || ""} member(s)
              </Button>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function TeamsTab() {
  const { can } = useSession();
  const teams = $api.useQuery("get", "/api/v1/org/teams/", { params: { query: { page_size: 100, is_archived: false } } });
  const [editing, setEditing] = useState<Team | "new" | null>(null);
  const [archiving, setArchiving] = useState<Team | null>(null);
  const refresh = useInvalidate("/api/v1/org/teams/");
  const archive = $api.useMutation("delete", "/api/v1/org/teams/{team_id}/", {
    onSuccess: () => { refresh(); setArchiving(null); toast.success("Team archived"); },
  });
  return (
    <>
      {can("team.manage") && (
        <div className="mb-4 flex justify-end"><Button onClick={() => setEditing("new")}><Plus /> New team</Button></div>
      )}
      <QueryState query={teams} isEmpty={(d) => !d.results.length}
                  empty={<EmptyState icon={<Users className="size-6" />} title="No teams yet" description="Teams group people; projects belong to a team." />}>
        {(data) => (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.results.map((t) => (
              <Card key={t.id} className="flex flex-col gap-3 p-5">
                <div>
                  <p className="text-lg font-bold text-ink">{t.name}</p>
                  {t.description && <p className="line-clamp-2 text-sm text-muted">{t.description}</p>}
                </div>
                <p className="text-sm text-muted">
                  Lead: <span className="font-semibold text-ink">{t.lead?.full_name ?? "—"}</span> · {t.member_count} members · {t.project_count} projects
                </p>
                {can("team.manage") && (
                  <div className="mt-auto flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setEditing(t)}>Manage</Button>
                    <Button variant="ghost" size="sm" onClick={() => setArchiving(t)}><Archive /> Archive</Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </QueryState>
      {editing && <TeamDialog team={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(archiving)} onOpenChange={() => setArchiving(null)} title={`Archive ${archiving?.name}?`}
                     description="Archive or move its projects first." confirmLabel="Archive" danger loading={archive.isPending}
                     onConfirm={() => archiving && archive.mutate({ params: { path: { team_id: archiving.id } } })} />
    </>
  );
}

function ProjectDialog({ project, onClose }: { project: Project | "new"; onClose: () => void }) {
  const refresh = useInvalidate("/api/v1/org/projects/", "/api/v1/org/projects/{project_id}/members/");
  const isNew = project === "new";
  const teams = $api.useQuery("get", "/api/v1/org/teams/", { params: { query: { page_size: 100, is_archived: false } } });
  const form = useForm<{ team_id: string; key: string; name: string; description: string; start_date: string; end_date: string; status: string }>({
    defaultValues: isNew
      ? { team_id: "", key: "", name: "", description: "", start_date: "", end_date: "", status: "ACTIVE" }
      : { team_id: project.team.id, key: project.key, name: project.name, description: project.description ?? "",
          start_date: project.start_date ?? "", end_date: project.end_date ?? "", status: project.status ?? "ACTIVE" },
  });
  const [add, setAdd] = useState<Person[]>([]);
  const members = $api.useQuery("get", "/api/v1/org/projects/{project_id}/members/",
    { params: { path: { project_id: isNew ? "" : project.id } } }, { enabled: !isNew });
  const fields = ["team_id", "key", "name", "end_date"] as const;
  const create = $api.useMutation("post", "/api/v1/org/projects/", {
    onSuccess: () => { refresh(); toast.success("Project created"); onClose(); },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, fields),
  });
  const update = $api.useMutation("patch", "/api/v1/org/projects/{project_id}/", {
    onSuccess: () => { refresh(); toast.success("Project saved"); },
    onError: (e: unknown) => applyFieldErrors(e, form.setError, fields),
  });
  const addMembers = $api.useMutation("post", "/api/v1/org/projects/{project_id}/members/", { onSuccess: () => { refresh(); setAdd([]); } });
  const removeMember = $api.useMutation("delete", "/api/v1/org/projects/{project_id}/members/{user_id}/", { onSuccess: refresh });
  const { errors } = form.formState;
  const memberIds = (members.data ?? []).map((m) => m.user.id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={isNew ? "New project" : `${project.key} · ${project.name}`}>
        <form className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={form.handleSubmit((v) => {
          const dates = { start_date: v.start_date || null, end_date: v.end_date || null };
          if (isNew) create.mutate({ body: { team_id: v.team_id, key: v.key, name: v.name, description: v.description, ...dates } });
          else update.mutate({ params: { path: { project_id: project.id } },
            body: { name: v.name, description: v.description, status: v.status as "ACTIVE", ...dates } });
        })}>
          <Field label="Team" htmlFor="p-team" error={errors.team_id?.message} required>
            <Select disabled={!isNew} {...form.register("team_id", { required: "Choose a team" })}>
              <option value="">Choose…</option>
              {(teams.data?.results ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          </Field>
          <Field label="Key" htmlFor="p-key" error={errors.key?.message} hint="2–10 letters/digits, used in task keys like WEB-42" required>
            <Input disabled={!isNew} className="uppercase" {...form.register("key", { required: "Enter a key" })} />
          </Field>
          <Field label="Name" htmlFor="p-name" error={errors.name?.message} required className="sm:col-span-2">
            <Input {...form.register("name", { required: "Enter a name" })} />
          </Field>
          <Field label="Description" htmlFor="p-desc" className="sm:col-span-2"><Textarea {...form.register("description")} /></Field>
          <Field label="Start date" htmlFor="p-start"><Input type="date" {...form.register("start_date")} /></Field>
          <Field label="End date" htmlFor="p-end" error={errors.end_date?.message}><Input type="date" {...form.register("end_date")} /></Field>
          {!isNew && (
            <Field label="Status" htmlFor="p-status">
              <Select {...form.register("status")}>
                {["ACTIVE", "ON_HOLD", "COMPLETED", "ARCHIVED"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
              </Select>
            </Field>
          )}
          <div className="sm:col-span-2"><Button type="submit" loading={create.isPending || update.isPending}>{isNew ? "Create project" : "Save"}</Button></div>
        </form>
        {!isNew && (
          <section className="mt-6">
            <h3 className="mb-2 text-sm font-bold text-ink">Members ({memberIds.length})</h3>
            <ul className="mb-3 max-h-48 divide-y divide-line overflow-y-auto rounded-xl border border-line">
              {(members.data ?? []).map((m) => (
                <li key={m.user.id} className="flex items-center gap-2 px-3 py-2 text-sm">
                  <Avatar name={m.user.full_name} className="size-7" />
                  <span className="min-w-0 flex-1 truncate font-semibold">{m.user.full_name}</span>
                  {project.owner?.id === m.user.id ? <Badge tone="primary">Owner</Badge> : (
                    <Button variant="ghost" size="sm" aria-label={`Remove ${m.user.full_name}`}
                            onClick={() => removeMember.mutate({ params: { path: { project_id: project.id, user_id: m.user.id } } })}>
                      <Trash2 />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            <PeoplePicker label="Members to add" value={add} onChange={setAdd} exclude={memberIds} />
            <Button size="sm" className="mt-2" disabled={!add.length} loading={addMembers.isPending}
                    onClick={() => addMembers.mutate({ params: { path: { project_id: project.id } }, body: { user_ids: add.map((p) => p.id) } })}>
              <Plus /> Add member(s)
            </Button>
          </section>
        )}
        <DialogFooter><Button variant="outline" onClick={onClose}>Close</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProjectsTab() {
  const { can } = useSession();
  const projects = $api.useQuery("get", "/api/v1/org/projects/", { params: { query: { page_size: 100 } } });
  const [editing, setEditing] = useState<Project | "new" | null>(null);
  return (
    <>
      {can("project.manage") && <div className="mb-4 flex justify-end"><Button onClick={() => setEditing("new")}><Plus /> New project</Button></div>}
      <QueryState query={projects} isEmpty={(d) => !d.results.length}
                  empty={<EmptyState icon={<FolderKanban className="size-6" />} title="No projects yet" />}>
        {(data) => (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.results.map((p) => (
              <Card key={p.id} className="flex flex-col gap-2 p-5">
                <div className="flex items-center gap-2">
                  <Badge tone="primary" className="font-mono">{p.key}</Badge>
                  {p.status !== "ACTIVE" && <Badge>{titleCase(p.status ?? "")}</Badge>}
                </div>
                <p className="text-lg font-bold text-ink">{p.name}</p>
                <p className="text-sm text-muted">{p.team.name} · owner {p.owner?.full_name ?? "—"}</p>
                <p className="text-sm text-muted">{p.member_count} members · {p.open_task_count} open tasks</p>
                {(can("project.manage") || can("project.member.manage")) && (
                  <Button variant="outline" size="sm" className="mt-auto self-start" onClick={() => setEditing(p)}>Manage</Button>
                )}
              </Card>
            ))}
          </div>
        )}
      </QueryState>
      {editing && <ProjectDialog project={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function TimeOffTab() {
  const { can } = useSession();
  const refresh = useInvalidate("/api/v1/hr/holidays/", "/api/v1/hr/leave/");
  const year = new Date().getFullYear();
  const holidays = $api.useQuery("get", "/api/v1/hr/holidays/", { params: { query: { year } } });
  const leave = $api.useQuery("get", "/api/v1/hr/leave/", { params: { query: { date_from: `${year}-01-01`, page_size: 100 } } });
  const holidayForm = useForm<{ date: string; name: string }>({ defaultValues: { date: "", name: "" } });
  const [person, setPerson] = useState<Person[]>([]);
  const leaveForm = useForm<{ date: string; kind: string; half_day: boolean; note: string }>({
    defaultValues: { date: "", kind: "ANNUAL", half_day: false, note: "" },
  });
  const addHoliday = $api.useMutation("post", "/api/v1/hr/holidays/", {
    onSuccess: () => { refresh(); holidayForm.reset(); toast.success("Holiday added"); },
    onError: (e: unknown) => applyFieldErrors(e, holidayForm.setError, ["date", "name"]),
  });
  const removeHoliday = $api.useMutation("delete", "/api/v1/hr/holidays/{holiday_id}/", { onSuccess: refresh });
  const addLeave = $api.useMutation("post", "/api/v1/hr/leave/", {
    onSuccess: () => { refresh(); leaveForm.reset(); setPerson([]); toast.success("Leave recorded"); },
    onError: (e: unknown) => applyFieldErrors(e, leaveForm.setError, ["date"]),
  });
  const removeLeave = $api.useMutation("delete", "/api/v1/hr/leave/{leave_id}/", { onSuccess: refresh });
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader title={`Holidays ${year}`} description="Excluded from everyone's capacity." />
        {can("holiday.manage") && (
          <form className="grid gap-3 border-b border-line p-4 sm:grid-cols-[150px_1fr_auto] sm:items-end" noValidate
                onSubmit={holidayForm.handleSubmit((body) => addHoliday.mutate({ body }))}>
            <Field label="Date" htmlFor="h-date" error={holidayForm.formState.errors.date?.message}>
              <Input type="date" {...holidayForm.register("date", { required: "Pick a date" })} />
            </Field>
            <Field label="Name" htmlFor="h-name"><Input {...holidayForm.register("name", { required: true })} /></Field>
            <Button type="submit" loading={addHoliday.isPending}><Plus /> Add</Button>
          </form>
        )}
        <QueryState query={holidays} isEmpty={(d) => !d.length} empty={<EmptyState icon={<CalendarOff className="size-6" />} title="No holidays this year" />}>
          {(items) => (
            <ul className="divide-y divide-line">
              {items.map((h) => (
                <li key={h.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                  <span className="w-28 font-semibold text-ink">{formatDate(h.date)}</span>
                  <span className="flex-1">{h.name}</span>
                  {can("holiday.manage") && (
                    <Button variant="ghost" size="sm" aria-label={`Remove ${h.name}`} onClick={() => removeHoliday.mutate({ params: { path: { holiday_id: h.id } } })}><Trash2 /></Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </Card>
      <Card>
        <CardHeader title="Leave" description="Reduces that person's capacity in workload views." />
        {can("leave.manage") && (
          <form className="grid gap-3 border-b border-line p-4" noValidate
                onSubmit={leaveForm.handleSubmit((v) => person[0] && addLeave.mutate({ body: { ...v, kind: v.kind as "ANNUAL", user_id: person[0].id } }))}>
            <PeoplePicker single label="Employee" value={person} onChange={setPerson} />
            <div className="grid gap-3 sm:grid-cols-3 sm:items-end">
              <Field label="Date" htmlFor="l-date" error={leaveForm.formState.errors.date?.message}>
                <Input type="date" {...leaveForm.register("date", { required: "Pick a date" })} />
              </Field>
              <Field label="Type" htmlFor="l-kind">
                <Select {...leaveForm.register("kind")}>
                  {["ANNUAL", "SICK", "UNPAID", "OTHER"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}
                </Select>
              </Field>
              <label className="flex h-11 items-center gap-2 text-sm font-semibold">
                <Checkbox checked={leaveForm.watch("half_day")} onCheckedChange={(v) => leaveForm.setValue("half_day", v === true)} /> Half day
              </label>
            </div>
            <Button type="submit" disabled={!person[0]} loading={addLeave.isPending} className="justify-self-start"><Plus /> Record leave</Button>
          </form>
        )}
        <QueryState query={leave} isEmpty={(d) => !d.results.length} empty={<EmptyState title="No leave recorded" />}>
          {(data) => (
            <ul className="divide-y divide-line">
              {data.results.map((l) => (
                <li key={l.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                  <span className="w-28 font-semibold text-ink">{formatDate(l.date)}</span>
                  <span className="min-w-0 flex-1 truncate">{l.user.full_name}</span>
                  <Badge>{titleCase(l.kind ?? "")}{l.half_day ? " · ½" : ""}</Badge>
                  {can("leave.manage") && (
                    <Button variant="ghost" size="sm" aria-label="Remove leave" onClick={() => removeLeave.mutate({ params: { path: { leave_id: l.id } } })}><Trash2 /></Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </Card>
    </div>
  );
}

export default function OrgPage() {
  return (
    <>
      <PageHeader title="Organization" description="Teams, projects, holidays and leave." />
      <Tabs defaultValue="teams">
        <TabsList className="mb-5">
          <TabsTrigger value="teams"><Users /> Teams</TabsTrigger>
          <TabsTrigger value="projects"><FolderKanban /> Projects</TabsTrigger>
          <TabsTrigger value="timeoff"><CalendarOff /> Holidays & leave</TabsTrigger>
        </TabsList>
        <TabsContent value="teams"><TeamsTab /></TabsContent>
        <TabsContent value="projects"><ProjectsTab /></TabsContent>
        <TabsContent value="timeoff"><TimeOffTab /></TabsContent>
      </Tabs>
    </>
  );
}
