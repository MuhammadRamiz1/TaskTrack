"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, KeyRound, LogOut, Mail, MailX, Plus, RotateCcw, Send, Trash2, UserCheck, UserMinus, UserX,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PasswordInput } from "@/components/auth/password-input";
import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { INVITE_TONE, USER_TONE } from "@/components/common/tones";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Avatar, Badge, Card, CardHeader, Checkbox } from "@/components/ui/primitives";
import { ErrorState, LoadingRows } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import { useSession } from "@/lib/auth/session";
import { formatDateTime, titleCase } from "@/lib/utils";
import { strongPassword } from "@/lib/validation";

type Action = "reset_link" | "deactivate" | "offboard" | "reactivate" | "revoke_sessions" | "revoke_invite" | null;

function TemporaryPasswordDialog({ userId, onClose }: { userId: string; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const set = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/temporary-password/", {
    onSuccess: () => { toast.success("Temporary password set. Share it with the employee securely."); onClose(); },
    onError: (e: unknown) => applyFieldErrors(e, (_n, err) => setError(err.message), ["password"]),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Set a temporary password"
                     description="All their sessions end and they must choose a new password at next sign-in. They get an email (without the password).">
        <form noValidate onSubmit={(e) => {
          e.preventDefault();
          const check = strongPassword.safeParse(password);
          if (!check.success) return setError(check.error.issues[0].message);
          set.mutate({ params: { path: { user_id: userId } }, body: { password } });
        }}>
          <Field label="Temporary password" htmlFor="temp-password" error={error ?? undefined}>
            <PasswordInput autoComplete="new-password" showStrength value={password}
                           onChange={(e) => { setPassword(e.target.value); setError(null); }} />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" loading={set.isPending}>Set password</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RolesCard({ userId, canEdit }: { userId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const path = { params: { path: { user_id: userId } } };
  const held = $api.useQuery("get", "/api/v1/hr/employees/{user_id}/roles/", path);
  const grantable = $api.useQuery("get", "/api/v1/hr/roles/", undefined, { enabled: canEdit });
  const teams = $api.useQuery("get", "/api/v1/org/teams/", { params: { query: { page_size: 100 } } }, { enabled: canEdit });
  const [roleId, setRoleId] = useState("");
  const [teamId, setTeamId] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/{user_id}/roles/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/{user_id}/"] });
  };
  const grant = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/roles/", {
    onSuccess: () => { refresh(); setRoleId(""); setTeamId(""); toast.success("Role granted"); },
  });
  const revoke = $api.useMutation("delete", "/api/v1/hr/employees/{user_id}/roles/{user_role_id}/", {
    onSuccess: () => { refresh(); toast.success("Role removed"); },
  });
  const teamName = (id?: string | null) => teams.data?.results.find((t) => t.id === id)?.name;
  return (
    <Card>
      <CardHeader title="Roles" description="Roles decide what this person can see and do. A role can be limited to one team." />
      <ul className="divide-y divide-line">
        {(held.data ?? []).map((r) => (
          <li key={r.user_role_id} className="flex items-center gap-3 px-5 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-ink">{r.name}</p>
              <p className="text-xs text-muted">{r.team_id ? `Team: ${teamName(r.team_id) ?? "…"}` : "Whole scope of the role"}</p>
            </div>
            {canEdit && (
              <Button variant="ghost" size="icon" aria-label={`Remove ${r.name}`}
                      onClick={() => revoke.mutate({ params: { path: { user_id: userId, user_role_id: r.user_role_id } } })}>
                <Trash2 />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form className="grid gap-3 border-t border-line p-4 sm:grid-cols-[1fr_1fr_auto]"
              onSubmit={(e) => { e.preventDefault(); grant.mutate({ ...path, body: { role_id: roleId, team_id: teamId || null } }); }}>
          <Select aria-label="Role to grant" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            <option value="">Add a role…</option>
            {(grantable.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
          <Select aria-label="Limit to team" value={teamId} onChange={(e) => setTeamId(e.target.value)}>
            <option value="">No team limit</option>
            {(teams.data?.results ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
          <Button type="submit" disabled={!roleId} loading={grant.isPending}><Plus /> Grant</Button>
        </form>
      )}
    </Card>
  );
}

function TeamsCard({ userId, current }: { userId: string; current: string[] }) {
  const qc = useQueryClient();
  const teams = $api.useQuery("get", "/api/v1/org/teams/", { params: { query: { page_size: 100, is_archived: false } } });
  const [selected, setSelected] = useState<string[]>(current);
  const allTeams = teams.data?.results ?? [];
  const dirty = [...selected].sort().join() !== [...current].sort().join();
  const save = $api.useMutation("put", "/api/v1/hr/employees/{user_id}/teams/", {
    onSuccess: (data) => {
      setSelected(data.map((t) => t.id));
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/org/teams/"] });
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/{user_id}/"] });
      toast.success("Teams updated");
    },
  });
  return (
    <Card>
      <CardHeader title="Teams" description="Team membership decides which team-scoped work this person sees." />
      <div className="flex flex-col gap-2 p-5">
        {allTeams.map((t) => {
          const checked = selected.includes(t.id);
          return (
            <label key={t.id} className="flex items-center gap-3 text-sm">
              <Checkbox checked={checked}
                        onCheckedChange={(v) => setSelected((s) => (v ? [...s, t.id] : s.filter((x) => x !== t.id)))} />
              <span className="font-semibold text-ink">{t.name}</span>
              <span className="text-muted">{t.member_count} members</span>
            </label>
          );
        })}
        <div className="mt-2">
          <Button size="sm" disabled={!dirty} loading={save.isPending}
                  onClick={() => save.mutate({ params: { path: { user_id: userId } }, body: { team_ids: selected } })}>
            Save teams
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function EmployeeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { can, user: me } = useSession();
  const path = { params: { path: { user_id: id } } };
  const employee = $api.useQuery("get", "/api/v1/hr/employees/{user_id}/", path);
  const [action, setAction] = useState<Action>(null);
  const [tempPassword, setTempPassword] = useState(false);
  const [manager, setManager] = useState<Person[]>([]);
  const profile = useForm<{ first_name: string; last_name: string; job_title: string }>();
  useEffect(() => {
    if (employee.data) {
      profile.reset({ first_name: employee.data.first_name, last_name: employee.data.last_name, job_title: employee.data.job_title });
      // eslint-disable-next-line react-hooks/set-state-in-effect -- seed picker from server data
      setManager(employee.data.manager ? [employee.data.manager] : []);
    }
  }, [employee.data, profile]);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/{user_id}/"] });
  const ok = (msg: string) => () => { refresh(); setAction(null); toast.success(msg); };
  const update = $api.useMutation("patch", "/api/v1/hr/employees/{user_id}/", { onSuccess: ok("Saved"),
    onError: (e: unknown) => applyFieldErrors(e, profile.setError, ["first_name", "last_name", "job_title"]) });
  const invite = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/invite/", { onSuccess: ok("Invite link sent") });
  const revokeInvite = $api.useMutation("delete", "/api/v1/hr/employees/{user_id}/invite/", { onSuccess: ok("Invite link revoked") });
  const resetLink = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/password-reset-link/", { onSuccess: ok("Reset link sent; all sessions ended") });
  const deactivate = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/deactivate/", { onSuccess: ok("Employee deactivated") });
  const offboard = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/offboard/", {
    onSuccess: (r) => { refresh(); setAction(null); toast.success(`Offboarded. ${r.tasks_flagged ?? 0} task(s) flagged for reassignment.`); },
  });
  const reactivate = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/reactivate/", { onSuccess: ok("Employee reactivated") });
  const revokeSessions = $api.useMutation("post", "/api/v1/hr/employees/{user_id}/revoke-sessions/", { onSuccess: ok("Signed out of all devices") });

  if (!employee.data) {
    return employee.isPending ? <LoadingRows /> : <ErrorState error={employee.error} onRetry={() => employee.refetch()} />;
  }
  const e = employee.data;
  const inviteState = e.invite;
  const self = me?.id === e.id;
  const active = e.status === "ACTIVE";
  const invited = e.status === "INVITED";

  return (
    <>
      <Link href="/hr/employees" className="mb-3 inline-flex items-center gap-1 text-sm font-semibold text-link">
        <ArrowLeft className="size-4" /> People
      </Link>
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center">
        <Avatar name={e.full_name} className="size-14 text-base" />
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-extrabold tracking-tight text-ink">{e.full_name}</h1>
          <p className="text-muted">{e.email} {e.job_title && `· ${e.job_title}`}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge tone={USER_TONE[e.status ?? "ACTIVE"]}>{titleCase(e.status ?? "")}</Badge>
            {e.totp_enabled && <Badge tone="success">2FA on</Badge>}
            {e.must_change_password && <Badge tone="warning">Must change password</Badge>}
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader title="Profile" />
            <form className="grid gap-4 p-5 sm:grid-cols-2" noValidate
                  onSubmit={profile.handleSubmit((body) => update.mutate({ ...path, body: { ...body, manager_id: manager[0]?.id ?? null } }))}>
              <Field label="First name" htmlFor="first_name" error={profile.formState.errors.first_name?.message}>
                <Input disabled={!can("employee.update")} {...profile.register("first_name")} />
              </Field>
              <Field label="Last name" htmlFor="last_name">
                <Input disabled={!can("employee.update")} {...profile.register("last_name")} />
              </Field>
              <Field label="Job title" htmlFor="job_title" className="sm:col-span-2">
                <Input disabled={!can("employee.update")} {...profile.register("job_title")} />
              </Field>
              {can("employee.assign_team") && (
                <div className="sm:col-span-2">
                  <p className="mb-1.5 text-sm font-semibold text-ink">Manager</p>
                  <PeoplePicker single label="Manager" value={manager} onChange={setManager} exclude={[e.id]} />
                </div>
              )}
              {can("employee.update") && <div><Button type="submit" loading={update.isPending}>Save</Button></div>}
            </form>
          </Card>
          <RolesCard userId={e.id} canEdit={can("employee.assign_role") && !self} />
          {can("employee.assign_team") && (
            <TeamsCard key={e.teams.map((t) => t.id).join()} userId={e.id} current={e.teams.map((t) => t.id)} />
          )}
        </div>

        <div className="flex flex-col gap-5">
          {invited && can("employee.invite") && (
            <Card>
              <CardHeader title="Invite link" action={<Badge tone={INVITE_TONE[inviteState.state]}>{titleCase(inviteState.state)}</Badge>} />
              <div className="flex flex-col gap-3 p-5 text-sm">
                {inviteState.state === "pending" && <p className="text-muted">Valid until {formatDateTime(inviteState.expires_at)}. Sent {inviteState.send_count} time(s).</p>}
                {inviteState.state === "expired" && <p className="text-warning">The link expired. Send a new one.</p>}
                {inviteState.state === "none" && <p className="text-muted">No invite has been sent yet.</p>}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" loading={invite.isPending} onClick={() => invite.mutate(path)}>
                    {inviteState.state === "none" ? <><Send /> Send invite</> : <><Mail /> Resend link</>}
                  </Button>
                  {inviteState.state === "pending" && (
                    <Button size="sm" variant="outline" onClick={() => setAction("revoke_invite")}><MailX /> Revoke link</Button>
                  )}
                </div>
              </div>
            </Card>
          )}
          {!self && (
            <Card>
              <CardHeader title="Access" description="HR cannot change the password of HR, admin or super admin accounts." />
              <div className="flex flex-col gap-2 p-5">
                {active && can("employee.reset_password") && (
                  <>
                    <Button variant="outline" className="justify-start" onClick={() => setAction("reset_link")}><KeyRound /> Email a password reset link</Button>
                    <Button variant="outline" className="justify-start" onClick={() => setTempPassword(true)}><RotateCcw /> Set a temporary password</Button>
                  </>
                )}
                {active && can("employee.deactivate") && (
                  <Button variant="outline" className="justify-start" onClick={() => setAction("revoke_sessions")}><LogOut /> Sign out of all devices</Button>
                )}
                {e.status !== "DEACTIVATED" && can("employee.deactivate") && (
                  <>
                    <Button variant="outline" className="justify-start" onClick={() => setAction("deactivate")}><UserX /> Deactivate</Button>
                    <Button variant="danger" className="justify-start" onClick={() => setAction("offboard")}><UserMinus /> Offboard</Button>
                  </>
                )}
                {e.status === "DEACTIVATED" && can("employee.deactivate") && (
                  <Button className="justify-start" onClick={() => setAction("reactivate")}><UserCheck /> Reactivate</Button>
                )}
                <dl className="mt-3 grid grid-cols-2 gap-1 text-xs text-muted">
                  <dt>Last sign-in</dt><dd className="text-right">{formatDateTime(e.last_login)}</dd>
                  <dt>Activated</dt><dd className="text-right">{formatDateTime(e.activated_at)}</dd>
                  {e.deactivated_at && <><dt>Deactivated</dt><dd className="text-right">{formatDateTime(e.deactivated_at)}</dd></>}
                </dl>
              </div>
            </Card>
          )}
        </div>
      </div>

      {tempPassword && <TemporaryPasswordDialog userId={e.id} onClose={() => setTempPassword(false)} />}
      <ConfirmDialog open={action === "reset_link"} onOpenChange={() => setAction(null)}
                     title="Email a reset link?" description="All of their sessions end now. The link expires in one hour."
                     confirmLabel="Send link" loading={resetLink.isPending} onConfirm={() => resetLink.mutate(path)} />
      <ConfirmDialog open={action === "revoke_invite"} onOpenChange={() => setAction(null)}
                     title="Revoke the invite link?" description="The link stops working immediately."
                     confirmLabel="Revoke" danger loading={revokeInvite.isPending} onConfirm={() => revokeInvite.mutate(path)} />
      <ConfirmDialog open={action === "revoke_sessions"} onOpenChange={() => setAction(null)}
                     title="Sign out of all devices?" confirmLabel="Sign out everywhere"
                     loading={revokeSessions.isPending} onConfirm={() => revokeSessions.mutate(path)} />
      <ConfirmDialog open={action === "deactivate"} onOpenChange={() => setAction(null)}
                     title={`Deactivate ${e.full_name}?`} description="They are signed out and cannot sign in. History is kept."
                     reasonLabel="Reason" confirmLabel="Deactivate" danger loading={deactivate.isPending}
                     onConfirm={(reason) => deactivate.mutate({ ...path, body: { reason } })} />
      <ConfirmDialog open={action === "offboard"} onOpenChange={() => setAction(null)}
                     title={`Offboard ${e.full_name}?`}
                     description="Deactivates the account, ends sessions, stops running timers and flags their open tasks for reassignment."
                     reasonLabel="Reason" confirmLabel="Offboard" danger loading={offboard.isPending}
                     onConfirm={(reason) => offboard.mutate({ ...path, body: { reason } })} />
      <ConfirmDialog open={action === "reactivate"} onOpenChange={() => setAction(null)}
                     title={`Reactivate ${e.full_name}?`} confirmLabel="Reactivate"
                     loading={reactivate.isPending} onConfirm={() => reactivate.mutate(path)} />
    </>
  );
}
