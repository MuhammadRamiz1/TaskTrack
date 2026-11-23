"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Card, CardHeader } from "@/components/ui/primitives";
import { $api } from "@/lib/api/client";
import { applyFieldErrors } from "@/lib/api/errors";
import { useMe, useSession } from "@/lib/auth/session";

const TIMEZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC"];

const schema = z.object({
  first_name: z.string().trim().min(1, "First name is required").max(100),
  last_name: z.string().trim().max(100),
  job_title: z.string().trim().max(120),
  timezone: z.string().min(1),
});

export default function ProfilePage() {
  const me = useMe();
  const { updateUser } = useSession();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { first_name: me.first_name, last_name: me.last_name, job_title: me.job_title, timezone: me.timezone },
  });
  const save = $api.useMutation("patch", "/api/v1/auth/me/", {
    onSuccess: (data) => {
      updateUser(data);
      form.reset(form.getValues());
      toast.success("Profile saved");
    },
    onError: (error) => applyFieldErrors(error, form.setError, ["first_name", "last_name", "job_title", "timezone"]),
  });
  const { errors } = form.formState;
  return (
    <Card className="max-w-2xl">
      <CardHeader title="Profile" description={me.email} />
      <form className="grid gap-4 p-5 sm:grid-cols-2" onSubmit={form.handleSubmit((body) => save.mutate({ body }))} noValidate>
        <Field label="First name" htmlFor="first_name" error={errors.first_name?.message} required>
          <Input autoComplete="given-name" {...form.register("first_name")} />
        </Field>
        <Field label="Last name" htmlFor="last_name" error={errors.last_name?.message}>
          <Input autoComplete="family-name" {...form.register("last_name")} />
        </Field>
        <Field label="Job title" htmlFor="job_title" error={errors.job_title?.message}>
          <Input {...form.register("job_title")} />
        </Field>
        <Field label="Time zone" htmlFor="timezone" error={errors.timezone?.message}>
          <Select {...form.register("timezone")}>
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending} disabled={!form.formState.isDirty}>
            Save profile
          </Button>
        </div>
      </form>
    </Card>
  );
}
