"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, Laptop, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { PasswordInput } from "@/components/auth/password-input";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/form";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { useMe, useSession } from "@/lib/auth/session";
import { setAccessToken } from "@/lib/auth/token";
import { timeAgo } from "@/lib/utils";
import { strongPassword } from "@/lib/validation";

const passwordSchema = z
  .object({ current_password: z.string().min(1, "Enter your current password"), new_password: strongPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

/** Message for errors that are not tied to a form field (field errors render inline). */
function generalError(error: unknown) {
  if (!error) return null;
  if (error instanceof ApiError && Object.keys(error.fieldErrors).length) return null;
  return errorMessage(error);
}

function ChangePassword() {
  const me = useMe();
  const { updateUser } = useSession();
  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });
  const change = $api.useMutation("post", "/api/v1/auth/password/change/", {
    meta: { silent: true },
    onSuccess: (data) => {
      setAccessToken(data.access);
      updateUser(data.user);
      form.reset();
      toast.success("Password changed. Other devices were signed out.");
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError) {
        for (const [field, message] of Object.entries(error.fieldErrors)) {
          if (field === "current_password" || field === "new_password") form.setError(field, { type: "server", message });
        }
      }
    },
  });
  const { errors } = form.formState;
  return (
    <Card>
      <CardHeader
        title="Password"
        description={me.must_change_password ? "Your password was reset by HR. Choose a new one to continue." : "Changing it signs you out everywhere else."}
      />
      <form
        className="flex flex-col gap-4 p-5"
        noValidate
        onSubmit={form.handleSubmit(({ current_password, new_password }) =>
          change.mutate({ body: { current_password, new_password } }),
        )}
      >
        {me.must_change_password && (
          <div role="alert" className="flex gap-2 rounded-xl bg-warning-soft p-3 text-sm text-warning">
            <ShieldAlert className="size-5 shrink-0" /> You must change your temporary password before using TaskTrack.
          </div>
        )}
        <FormError message={generalError(change.error)} />
        <Field label="Current password" htmlFor="current_password" error={errors.current_password?.message}>
          <PasswordInput autoComplete="current-password" {...form.register("current_password")} />
        </Field>
        <Field label="New password" htmlFor="new_password" error={errors.new_password?.message}>
          <PasswordInput autoComplete="new-password" showStrength {...form.register("new_password")} value={form.watch("new_password")} />
        </Field>
        <Field label="Confirm new password" htmlFor="confirm" error={errors.confirm?.message}>
          <PasswordInput autoComplete="new-password" {...form.register("confirm")} />
        </Field>
        <div>
          <Button type="submit" loading={change.isPending}>
            <KeyRound /> Change password
          </Button>
        </div>
      </form>
    </Card>
  );
}

function TwoFactor() {
  const me = useMe();
  const { updateUser } = useSession();
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const refreshMe = async () => {
    const res = await qc.fetchQuery($api.queryOptions("get", "/api/v1/auth/me/"));
    updateUser(res);
  };
  const begin = $api.useMutation("post", "/api/v1/auth/2fa/setup/", { onSuccess: (d) => setSetup(d) });
  const confirm = $api.useMutation("post", "/api/v1/auth/2fa/confirm/", {
    onSuccess: async (d) => {
      setCodes(d.recovery_codes);
      setSetup(null);
      setCode("");
      // An enrolment-only token is upgraded on the next refresh.
      const { refreshSession } = await import("@/lib/auth/token");
      await refreshSession();
      toast.success("Two-factor authentication is on");
    },
  });
  const disable = $api.useMutation("post", "/api/v1/auth/2fa/disable/", {
    onSuccess: async () => {
      await refreshMe();
      setCode("");
      setPassword("");
      toast.success("Two-factor authentication is off");
    },
  });
  const regenerate = $api.useMutation("post", "/api/v1/auth/2fa/recovery-codes/", {
    onSuccess: (d) => {
      setCodes(d.recovery_codes);
      setCode("");
    },
  });

  return (
    <Card>
      <CardHeader
        title="Two-factor authentication"
        description="Use an authenticator app (Google Authenticator, 1Password, Authy) for a second sign-in step."
        action={me.totp_enabled ? <Badge tone="success"><ShieldCheck className="size-3.5" /> On</Badge> : <Badge>Off</Badge>}
      />
      <div className="flex flex-col gap-4 p-5" id="2fa">
        {me.mfa_enrolment_required && (
          <div role="alert" className="rounded-xl bg-warning-soft p-3 text-sm text-warning">
            Your company requires two-factor authentication. Set it up to continue.
          </div>
        )}
        {codes && (
          <div className="rounded-xl border border-primary-200 bg-primary-50 p-4">
            <p className="font-semibold text-ink">Save your recovery codes</p>
            <p className="mb-3 text-sm text-muted">Each code works once if you lose your phone. They will not be shown again.</p>
            <ul className="grid grid-cols-2 gap-2 font-mono text-sm sm:grid-cols-5">
              {codes.map((c) => (
                <li key={c} className="rounded-lg bg-surface px-2 py-1 text-center">{c}</li>
              ))}
            </ul>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => void navigator.clipboard.writeText(codes.join("\n"))}>
              Copy codes
            </Button>
          </div>
        )}
        {!me.totp_enabled && !setup && (
          <div>
            <Button loading={begin.isPending} onClick={() => begin.mutate({})}>Set up two-factor</Button>
          </div>
        )}
        {setup && (
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); confirm.mutate({ body: { code } }); }}>
            <p className="text-sm text-muted">
              Add this key in your authenticator app (or open the link on your phone), then enter the 6-digit code.
            </p>
            <code className="break-all rounded-xl bg-surface-2 px-3 py-2 font-mono text-sm">{setup.secret}</code>
            <a href={setup.otpauth_uri} className="text-sm font-semibold text-link underline">Open in authenticator app</a>
            <Field label="6-digit code" htmlFor="totp-code">
              <Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <div><Button type="submit" loading={confirm.isPending}>Turn on</Button></div>
          </form>
        )}
        {me.totp_enabled && (
          <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end" onSubmit={(e) => e.preventDefault()}>
            <Field label="Current code" htmlFor="totp-manage-code">
              <Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <Field label="Password (to turn off)" htmlFor="totp-password">
              <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="button" variant="outline" loading={regenerate.isPending} disabled={!code}
                    onClick={() => regenerate.mutate({ body: { code } })}>
              New recovery codes
            </Button>
            <Button type="button" variant="danger" loading={disable.isPending} disabled={!code || !password}
                    onClick={() => disable.mutate({ body: { code, password } })}>
              Turn off
            </Button>
          </form>
        )}
      </div>
    </Card>
  );
}

function Sessions() {
  const qc = useQueryClient();
  const { logout } = useSession();
  const sessions = $api.useQuery("get", "/api/v1/auth/sessions/");
  const revoke = $api.useMutation("delete", "/api/v1/auth/sessions/{session_id}/", {
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/auth/sessions/"] });
      toast.success("Device signed out");
    },
  });
  return (
    <Card>
      <CardHeader
        title="Signed-in devices"
        action={<Button variant="outline" size="sm" onClick={() => void logout(true)}>Sign out everywhere</Button>}
      />
      <QueryState query={sessions} rows={2}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.map((s) => (
              <li key={s.id} className="flex items-center gap-3 px-5 py-3">
                <Laptop className="size-5 text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{s.user_agent || "Unknown device"}</p>
                  <p className="text-xs text-muted">{s.ip ?? "—"} · active {timeAgo(s.last_used_at)}</p>
                </div>
                {s.current ? (
                  <Badge tone="success">This device</Badge>
                ) : (
                  <Button variant="ghost" size="sm" loading={revoke.isPending && revoke.variables?.params.path.session_id === s.id}
                          onClick={() => revoke.mutate({ params: { path: { session_id: s.id } } })}>
                    Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Card>
  );
}

export default function SecurityPage() {
  const me = useMe();
  const locked = me.must_change_password;
  return (
    <div className="grid max-w-3xl gap-5">
      <ChangePassword />
      {!locked && <TwoFactor />}
      {!locked && !me.mfa_enrolment_required && <Sessions />}
    </div>
  );
}
