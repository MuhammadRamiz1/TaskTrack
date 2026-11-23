"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthShell } from "@/components/auth/auth-shell";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/form";
import { EmptyState } from "@/components/ui/states";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { email } from "@/lib/validation";

const schema = z.object({ email });

export default function ForgotPasswordPage() {
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { email: "" } });
  const send = useMutation({
    meta: { silent: true },
    mutationFn: async (values: z.infer<typeof schema>) =>
      (await api.POST("/api/v1/auth/password/forgot/", { body: values })).data!,
  });
  return (
    <AuthShell title="Reset your password" subtitle="We'll email you a link to choose a new one.">
      {send.isSuccess ? (
        <EmptyState
          icon={<MailCheck className="size-6" />}
          title="Check your email"
          description="If an account exists for that address, a reset link is on its way. It expires in one hour."
          action={
            <Button asChild variant="outline">
              <Link href="/login">Back to sign in</Link>
            </Button>
          }
        />
      ) : (
        <form onSubmit={form.handleSubmit((v) => send.mutate(v))} className="flex flex-col gap-4" noValidate>
          <FormError message={send.error ? errorMessage(send.error) : null} />
          <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
            <Input type="email" autoComplete="email" {...form.register("email")} />
          </Field>
          <Button type="submit" size="lg" loading={send.isPending}>
            Send reset link
          </Button>
          <Link href="/login" className="text-center text-sm font-semibold text-link hover:underline">
            Back to sign in
          </Link>
        </form>
      )}
    </AuthShell>
  );
}
