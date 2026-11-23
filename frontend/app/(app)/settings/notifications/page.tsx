"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, Switch } from "@/components/ui/primitives";
import { QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Pref = components["schemas"]["Preference"];

export default function NotificationSettingsPage() {
  const qc = useQueryClient();
  const prefs = $api.useQuery("get", "/api/v1/notifications/preferences/");
  const [draft, setDraft] = useState<Pref[]>([]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seed the editable copy from the server
    if (prefs.data) setDraft(prefs.data);
  }, [prefs.data]);
  const save = $api.useMutation("put", "/api/v1/notifications/preferences/", {
    onSuccess: (data) => {
      qc.setQueryData(["get", "/api/v1/notifications/preferences/"], data);
      toast.success("Notification settings saved");
    },
  });
  const dirty = JSON.stringify(draft) !== JSON.stringify(prefs.data ?? []);
  const set = (eventType: string, key: "in_app" | "email", value: boolean) =>
    setDraft((d) => d.map((p) => (p.event_type === eventType ? { ...p, [key]: value } : p)));

  return (
    <Card className="max-w-3xl">
      <CardHeader
        title="Notifications"
        description="Choose what reaches you in the app and by email."
        action={
          <Button
            loading={save.isPending}
            disabled={!dirty}
            onClick={() => save.mutate({ body: { preferences: draft.map(({ event_type, in_app, email }) => ({ event_type, in_app, email })) } })}
          >
            Save
          </Button>
        }
      />
      <QueryState query={prefs}>
        {() => (
          <table className="w-full text-sm">
            <caption className="sr-only">Notification channels per event</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="px-5 py-3 font-semibold">Event</th>
                <th scope="col" className="w-20 px-2 py-3 text-center font-semibold">In app</th>
                <th scope="col" className="w-20 px-5 py-3 text-center font-semibold">Email</th>
              </tr>
            </thead>
            <tbody>
              {draft.map((p) => (
                <tr key={p.event_type} className="border-b border-line last:border-0">
                  <th scope="row" className="px-5 py-3 text-left font-medium text-ink">{p.label}</th>
                  <td className="px-2 py-3 text-center">
                    <Switch checked={p.in_app} onCheckedChange={(v) => set(p.event_type, "in_app", v)}
                            aria-label={`${p.label}: in app`} />
                  </td>
                  <td className="px-5 py-3 text-center">
                    <Switch checked={p.email} onCheckedChange={(v) => set(p.event_type, "email", v)}
                            aria-label={`${p.label}: email`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </Card>
  );
}
