"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { AuthShell } from "@/components/auth/auth-shell";
import { InvalidLink } from "@/components/auth/invalid-link";
import { PasswordInput } from "@/components/auth/password-input";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/form";
import { LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api/client";
import { applyFieldErrors, errorMessage } from "@/lib/api/errors";
import { useSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/utils";
import { newPasswordForm } from "@/lib/validation";

type Values = z.infer<typeof newPasswordForm>;

export default function AcceptInvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { startSession } = useSession();
  const invite = useQuery({
    queryKey: ["invite", token],
    retry: false,
    queryFn: async () =>
      (await api.GET("/api/v1/auth/invites/{token}/", { params: { path: { token } } })).data!,
  });
  const form = useForm<Values>({ resolver: zodResolver(newPasswordForm), defaultValues: { password: "", confirm: "" } });
  const accept = useMutation({
    meta: { silent: true },
    mutationFn: async (values: Values) =>
      (await api.POST("/api/v1/auth/invites/accept/", { body: { token, password: values.password } })).data!,
    onSuccess: (data) => {
      startSession(data.access, data.user);
      router.replace("/");
    },
    onError: (error) => applyFieldErrors(error, form.setError, ["password"]),
  });

  return (
    <AuthShell
      title="Set up your account"
      subtitle={invite.data ? `You're joining ${invite.data.company_name}.` : "Choose a password to get started."}
    >
      {invite.isPending && <LoadingRows rows={3} />}
      {invite.error && <InvalidLink message={errorMessage(invite.error)} />}
      {invite.data && (
        <form onSubmit={form.handleSubmit((v) => accept.mutate(v))} className="flex flex-col gap-4" noValidate>
          <div className="rounded-xl bg-surface-2 px-4 py-3 text-sm">
            <p className="font-semibold text-ink">{invite.data.email}</p>
            <p className="text-muted">Link valid until {formatDateTime(invite.data.expires_at)}</p>
          </div>
          <FormError message={accept.error && !form.formState.errors.password ? errorMessage(accept.error) : null} />
          <Field label="New password" htmlFor="password" error={form.formState.errors.password?.message}
                 hint="At least 12 characters, using 3 of: lowercase, uppercase, digits, symbols.">
            <PasswordInput autoComplete="new-password" showStrength {...form.register("password")}
                           value={form.watch("password")} />
          </Field>
          <Field label="Confirm password" htmlFor="confirm" error={form.formState.errors.confirm?.message}>
            <PasswordInput autoComplete="new-password" {...form.register("confirm")} />
          </Field>
          <Button type="submit" size="lg" loading={accept.isPending}>
            Activate account
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
