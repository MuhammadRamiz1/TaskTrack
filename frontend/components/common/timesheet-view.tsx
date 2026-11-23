"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Pencil, Send, Trash2, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { TIMESHEET_TONE } from "@/components/common/tones";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { $api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useMe, useSession } from "@/lib/auth/session";
import { formatDate, formatDateTime, formatDuration, titleCase } from "@/lib/utils";

type Sheet = components["schemas"]["TimesheetDetail"];
type Entry = components["schemas"]["EntryOutput"];

function toLocalInput(iso: string) {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function EditEntry({ entry, onClose }: { entry: Entry; onClose: () => void }) {
  const qc = useQueryClient();
  const [start, setStart] = useState(toLocalInput(entry.started_at));
  const [end, setEnd] = useState(entry.ended_at ? toLocalInput(entry.ended_at) : "");
  const [note, setNote] = useState(entry.note ?? "");
  const save = $api.useMutation("patch", "/api/v1/time/entries/{entry_id}/", {
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["get"] }); toast.success("Entry updated"); onClose(); },
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`Edit time on ${entry.task.key}`}>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ params: { path: { entry_id: entry.id } }, body: {
            version: entry.version!, started_at: new Date(start).toISOString(), ended_at: new Date(end).toISOString(), note } });
        }}>
          <Field label="Start" htmlFor="e-start"><Input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></Field>
          <Field label="End" htmlFor="e-end"><Input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required /></Field>
          <Field label="Note" htmlFor="e-note" className="sm:col-span-2"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={save.isPending}>Save</Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Weekly timesheet: entries grouped by day, submit (owner) or approve/reject (approver). */
export function TimesheetView({ sheet }: { sheet: Sheet }) {
  const me = useMe();
  const { can } = useSession();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Entry | null>(null);
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["get"] });
  const path = { params: { path: { timesheet_id: sheet.id } } };
  const done = (msg: string) => () => { refresh(); setDeciding(null); setConfirmSubmit(false); toast.success(msg); };
  const submit = $api.useMutation("post", "/api/v1/time/timesheets/{timesheet_id}/submit/", { onSuccess: done("Timesheet submitted") });
  const approve = $api.useMutation("post", "/api/v1/time/timesheets/{timesheet_id}/approve/", { onSuccess: done("Timesheet approved") });
  const reject = $api.useMutation("post", "/api/v1/time/timesheets/{timesheet_id}/reject/", { onSuccess: done("Timesheet rejected") });
  const remove = $api.useMutation("delete", "/api/v1/time/entries/{entry_id}/", { onSuccess: done("Entry deleted") });
  const own = sheet.user.id === me.id;
  const editable = sheet.status === "OPEN" || sheet.status === "REJECTED";
  const byDay = new Map<string, Entry[]>();
  for (const e of sheet.entries) byDay.set(e.work_date, [...(byDay.get(e.work_date) ?? []), e]);
  const lastDecision = sheet.approvals.at(-1);

  return (
    <Card>
      <CardHeader
        title={`Week of ${formatDate(sheet.period_start)}`}
        description={`${sheet.user.full_name} · ${formatDuration(sheet.total_seconds)} logged`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={TIMESHEET_TONE[sheet.status ?? "OPEN"]}>{titleCase(sheet.status ?? "")}</Badge>
            {own && editable && sheet.entries.length > 0 && <Button size="sm" onClick={() => setConfirmSubmit(true)}><Send /> Submit</Button>}
            {!own && sheet.status === "SUBMITTED" && can("timesheet.approve") && (
              <>
                <Button size="sm" onClick={() => setDeciding("approve")}><CheckCircle2 /> Approve</Button>
                <Button size="sm" variant="outline" onClick={() => setDeciding("reject")}><XCircle /> Reject</Button>
              </>
            )}
          </div>
        }
      />
      {lastDecision?.decision === "REJECTED" && sheet.status === "REJECTED" && (
        <p role="status" className="mx-5 mt-4 rounded-xl bg-danger-soft p-3 text-sm text-danger">
          Rejected by {lastDecision.approver.full_name}: {lastDecision.comment}
        </p>
      )}
      {sheet.entries.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted">No time logged this week. Start a timer from a task or log time manually.</p>
      ) : (
        <div className="divide-y divide-line">
          {[...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => (
            <section key={day} className="px-5 py-3">
              <h3 className="mb-2 flex justify-between text-sm font-bold text-ink">
                {formatDate(day, "EEEE d MMM")}
                <span className="tabular-nums text-muted">{formatDuration(list.reduce((s, e) => s + (e.duration_seconds ?? 0), 0))}</span>
              </h3>
              <ul className="flex flex-col gap-1.5">
                {list.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-2 px-3 py-2 text-sm">
                    <Link href={`/tasks/${e.task.id}`} className="min-w-0 flex-1 truncate font-semibold text-ink hover:underline">
                      <span className="font-mono text-xs text-muted">{e.task.key}</span> {e.task.title}
                    </Link>
                    <span className="text-xs text-muted">{formatDateTime(e.started_at).split(", ")[1]}–{e.ended_at ? formatDateTime(e.ended_at).split(", ")[1] : "now"}</span>
                    <Badge>{titleCase(e.source ?? "")}</Badge>
                    <span className="w-16 text-right font-semibold tabular-nums">{e.ended_at ? formatDuration(e.duration_seconds) : "running"}</span>
                    {e.status === "DRAFT" && (own || can("time.edit_others")) && (
                      <span className="flex">
                        <Button variant="ghost" size="sm" aria-label="Edit entry" onClick={() => setEditing(e)}><Pencil /></Button>
                        <Button variant="ghost" size="sm" aria-label="Delete entry" onClick={() => remove.mutate({ params: { path: { entry_id: e.id } } })}><Trash2 /></Button>
                      </span>
                    )}
                    {e.note && <p className="w-full text-xs text-muted">{e.note}</p>}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      {editing && <EditEntry entry={editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={confirmSubmit} onOpenChange={setConfirmSubmit} title="Submit this week?"
                     description="Entries are locked until your approver decides." confirmLabel="Submit"
                     loading={submit.isPending} onConfirm={() => submit.mutate(path)} />
      <ConfirmDialog open={deciding === "approve"} onOpenChange={() => setDeciding(null)} title="Approve timesheet?"
                     reasonLabel="Comment (optional)" confirmLabel="Approve" loading={approve.isPending}
                     onConfirm={(comment) => approve.mutate({ ...path, body: { comment } })} />
      <ConfirmDialog open={deciding === "reject"} onOpenChange={() => setDeciding(null)} title="Reject timesheet?"
                     description="Entries become editable again." reasonLabel="What needs fixing?" reasonRequired
                     confirmLabel="Reject" danger loading={reject.isPending}
                     onConfirm={(comment) => reject.mutate({ ...path, body: { comment } })} />
    </Card>
  );
}
