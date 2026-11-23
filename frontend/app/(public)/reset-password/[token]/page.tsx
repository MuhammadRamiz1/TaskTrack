"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { AuthShell } from "@/components/auth/auth-shell";
import { InvalidLink } from "@/components/auth/invalid-link";
import { PasswordInput } from "@/components/auth/password-input";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/form";
import { EmptyState, LoadingRows } from "@/components/ui/states";
import { api } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { newPasswordForm } from "@/lib/validation";

type Values = z.infer<typeof newPasswordForm>;

export default function ResetPasswordPage() {
  const { token } = useParams<{ token: string }>();
  const link = useQuery({
    queryKey: ["reset-link", token],
    retry: false,
    queryFn: async () =>
      (await api.GET("/api/v1/auth/password/reset/{token}/", { params: { path: { token } } })).data!,
  });
  const form = useForm<Values>({ resolver: zodResolver(newPasswordForm), defaultValues: { password: "", confirm: "" } });
  const reset = useMutation({
    meta: { silent: true },
    mutationFn: async (values: Values) =>
      (await api.POST("/api/v1/auth/password/reset/", { body: { token, new_password: values.password } })).data!,
    onError: (error) => {
      const message = error instanceof ApiError ? error.fieldErrors.new_password : undefined;
      if (message) form.setError("password", { type: "server", message });
    },
  });

  return (
    <AuthShell title="Choose a new password" subtitle={link.data ? `For ${link.data.email}` : undefined}>
      {link.isPending && <LoadingRows rows={3} />}
      {link.error && <InvalidLink message={errorMessage(link.error)} />}
      {link.data && reset.isSuccess && (
        <EmptyState
          icon={<CheckCircle2 className="size-6" />}
          title="Password updated"
          description="You were signed out of all devices. Sign in with your new password."
          action={
            <Button asChild>
              <Link href="/login">Sign in</Link>
            </Button>
          }
        />
      )}
      {link.data && !reset.isSuccess && (
        <form onSubmit={form.handleSubmit((v) => reset.mutate(v))} className="flex flex-col gap-4" noValidate>
          <FormError message={reset.error ? errorMessage(reset.error) : null} />
          <Field label="New password" htmlFor="password" error={form.formState.errors.password?.message}
                 hint="At least 12 characters, using 3 of: lowercase, uppercase, digits, symbols.">
            <PasswordInput autoComplete="new-password" showStrength {...form.register("password")}
                           value={form.watch("password")} />
          </Field>
          <Field label="Confirm password" htmlFor="confirm" error={form.formState.errors.confirm?.message}>
            <PasswordInput autoComplete="new-password" {...form.register("confirm")} />
          </Field>
          <Button type="submit" size="lg" loading={reset.isPending}>
            Update password
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
