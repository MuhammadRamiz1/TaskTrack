"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthShell } from "@/components/auth/auth-shell";
import { PasswordInput } from "@/components/auth/password-input";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/form";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useSession } from "@/lib/auth/session";
import type { Me } from "@/lib/auth/token";
import { email } from "@/lib/validation";

const credentialsSchema = z.object({ email, password: z.string().min(1, "Password is required") });
const codeSchema = z.object({ code: z.string().trim().min(6, "Enter the 6-digit code or a recovery code") });

function safeNext(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { startSession } = useSession();
  const [mfaToken, setMfaToken] = useState<string | null>(null);

  const finish = (access: string, user: Me) => {
    startSession(access, user);
    router.replace(safeNext(params.get("next")));
  };

  const credentials = useForm<z.infer<typeof credentialsSchema>>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { email: "", password: "" },
  });
  const login = useMutation({
    meta: { silent: true },
    mutationFn: async (values: z.infer<typeof credentialsSchema>) =>
      (await api.POST("/api/v1/auth/login/", { body: values })).data!,
    onSuccess: (data) => {
      if (data.mfa_required && data.mfa_token) setMfaToken(data.mfa_token);
      else if (data.access && data.user) finish(data.access, data.user);
    },
  });

  const codeForm = useForm<z.infer<typeof codeSchema>>({ resolver: zodResolver(codeSchema), defaultValues: { code: "" } });
  const verify = useMutation({
    meta: { silent: true },
    mutationFn: async ({ code }: { code: string }) =>
      (await api.POST("/api/v1/auth/2fa/verify/", { body: { mfa_token: mfaToken!, code } })).data!,
    onSuccess: (data) => finish(data.access, data.user),
  });

  if (mfaToken) {
    return (
      <form onSubmit={codeForm.handleSubmit((v) => verify.mutate(v))} className="flex flex-col gap-4" noValidate>
        <p className="text-sm text-muted">Enter the code from your authenticator app, or one of your recovery codes.</p>
        <FormError message={verify.error ? errorMessage(verify.error) : null} />
        <Field label="Verification code" htmlFor="code" error={codeForm.formState.errors.code?.message}>
          <Input autoComplete="one-time-code" inputMode="text" autoFocus {...codeForm.register("code")} />
        </Field>
        <Button type="submit" size="lg" loading={verify.isPending}>
          Verify and sign in
        </Button>
        <Button type="button" variant="link" onClick={() => setMfaToken(null)}>
          Use a different account
        </Button>
      </form>
    );
  }

  const { errors } = credentials.formState;
  return (
    <form onSubmit={credentials.handleSubmit((v) => login.mutate(v))} className="flex flex-col gap-4" noValidate>
      <FormError message={login.error ? errorMessage(login.error) : null} />
      <Field label="Email" htmlFor="email" error={errors.email?.message}>
        <Input type="email" autoComplete="email" placeholder="you@company.com" {...credentials.register("email")} />
      </Field>
      <Field label="Password" htmlFor="password" error={errors.password?.message}>
        <PasswordInput autoComplete="current-password" {...credentials.register("password")} />
      </Field>
      <div className="-mt-1 flex justify-end">
        <Link href="/forgot-password" className="text-sm font-semibold text-link hover:underline">
          Forgot password?
        </Link>
      </div>
      <Button type="submit" size="lg" loading={login.isPending}>
        Sign in
      </Button>
      <p className="text-center text-sm text-muted">
        New here? Accounts are created by your HR team; check your email for an invite link.
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthShell title="Welcome back 👋" subtitle="Sign in to keep your tasks on track.">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
