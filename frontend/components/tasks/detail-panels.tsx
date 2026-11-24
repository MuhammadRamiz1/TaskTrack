"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AtSign, CheckCircle2, Download, FileUp, GitBranch, Link2, MessageSquare, Paperclip, Plus, Trash2, XCircle,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ConfirmDialog, Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Avatar, Badge, Card, CardHeader, Checkbox } from "@/components/ui/primitives";
import { EmptyState, QueryState } from "@/components/ui/states";
import { $api, downloadFile, uploadFile } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useMe, useSession } from "@/lib/auth/session";
import { cn, formatBytes, formatDateTime, formatDuration, timeAgo, titleCase } from "@/lib/utils";

import { StatusBadge } from "./meta";

export type TaskDetail = components["schemas"]["TaskDetail"];

function useTaskRefresh() {
  const qc = useQueryClient();
  return () => {
    for (const p of [
      "/api/v1/tasks/{task_id}/", "/api/v1/tasks/{task_id}/comments/", "/api/v1/tasks/{task_id}/attachments/",
      "/api/v1/tasks/{task_id}/activity/", "/api/v1/tasks/{task_id}/reviews/", "/api/v1/tasks/{task_id}/time-entries/",
      "/api/v1/tasks/", "/api/v1/time/timer/current/",
    ]) void qc.invalidateQueries({ queryKey: ["get", p] });
  };
}

/* ----------------------------------------------------------------- Checklists */

export function ChecklistsPanel({ task }: { task: TaskDetail }) {
  const { can } = useSession();
  const refresh = useTaskRefresh();
  const path = { params: { path: { task_id: task.id } } };
  const manage = can("task.checklist.manage") && !task.is_read_only && task.status !== "IN_REVIEW";
  const tick = can("task.checklist.complete") && !task.is_read_only && task.status !== "IN_REVIEW";
  const [newList, setNewList] = useState("");
  const [newItem, setNewItem] = useState<Record<string, string>>({});
  const addList = $api.useMutation("post", "/api/v1/tasks/{task_id}/checklists/", { onSuccess: () => { refresh(); setNewList(""); } });
  const addItem = $api.useMutation("post", "/api/v1/tasks/{task_id}/checklists/{checklist_id}/items/", { onSuccess: refresh });
  const updateItem = $api.useMutation("patch", "/api/v1/tasks/{task_id}/checklist-items/{item_id}/", { onSuccess: refresh });
  const removeItem = $api.useMutation("delete", "/api/v1/tasks/{task_id}/checklist-items/{item_id}/", { onSuccess: refresh });
  const removeList = $api.useMutation("delete", "/api/v1/tasks/{task_id}/checklists/{checklist_id}/", { onSuccess: refresh });
  const all = task.checklists.flatMap((c) => c.items);
  const done = all.filter((i) => i.is_done).length;
  if (!task.checklists.length && !manage) return null;
  return (
    <Card>
      <CardHeader title="Checklist" description={all.length ? `${done} of ${all.length} done` : undefined} />
      <div className="flex flex-col gap-4 p-5">
        {all.length > 0 && (
          <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={done} aria-valuemax={all.length}
               aria-label="Checklist progress">
            <div className="h-full rounded-full bg-primary-500 transition-[width]" style={{ width: `${(done / all.length) * 100}%` }} />
          </div>
        )}
        {task.checklists.map((list) => (
          <section key={list.id}>
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-sm font-bold text-ink">{list.title}</h3>
              {manage && (
                <Button variant="ghost" size="sm" aria-label={`Delete ${list.title}`}
                        onClick={() => removeList.mutate({ params: { path: { task_id: task.id, checklist_id: list.id } } })}><Trash2 /></Button>
              )}
            </div>
            <ul className="flex flex-col">
              {list.items.map((item) => (
                <li key={item.id} className="group flex min-h-10 items-center gap-3 rounded-lg px-1 hover:bg-hover">
                  <Checkbox id={`item-${item.id}`} checked={item.is_done} disabled={!tick || updateItem.isPending}
                            onCheckedChange={(v) => updateItem.mutate({ params: { path: { task_id: task.id, item_id: item.id } }, body: { is_done: v === true } })} />
                  <label htmlFor={`item-${item.id}`} className={cn("flex-1 text-sm", item.is_done && "text-muted line-through")}>
                    {item.text}
                    {item.is_required && <Badge tone="warning" className="ml-2">Required</Badge>}
                  </label>
                  {manage && (
                    <Button variant="ghost" size="sm" className="opacity-60 group-hover:opacity-100" aria-label={`Delete ${item.text}`}
                            onClick={() => removeItem.mutate({ params: { path: { task_id: task.id, item_id: item.id } } })}><Trash2 /></Button>
                  )}
                </li>
              ))}
            </ul>
            {manage && (
              <form className="mt-1.5 flex gap-2" onSubmit={(e) => {
                e.preventDefault();
                const text = newItem[list.id]?.trim();
                if (!text) return;
                const required = text.startsWith("!");
                addItem.mutate({ params: { path: { task_id: task.id, checklist_id: list.id } },
                  body: { text: required ? text.slice(1).trim() : text, is_required: required } });
                setNewItem((s) => ({ ...s, [list.id]: "" }));
              }}>
                <Input aria-label={`Add item to ${list.title}`} placeholder="Add an item (start with ! to make it required)"
                       value={newItem[list.id] ?? ""} onChange={(e) => setNewItem((s) => ({ ...s, [list.id]: e.target.value }))} />
                <Button type="submit" variant="outline" size="icon" aria-label="Add item"><Plus /></Button>
              </form>
            )}
          </section>
        ))}
        {manage && (
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (newList.trim()) addList.mutate({ ...path, body: { title: newList.trim() } }); }}>
            <Input aria-label="New checklist title" placeholder="New checklist" value={newList} onChange={(e) => setNewList(e.target.value)} />
            <Button type="submit" variant="outline" loading={addList.isPending}><Plus /> Checklist</Button>
          </form>
        )}
      </div>
    </Card>
  );
}

/* --------------------------------------------------------- Subtasks & dependencies */

export function RelationsPanel({ task, onNewSubtask }: { task: TaskDetail; onNewSubtask: () => void }) {
  const { can } = useSession();
  const refresh = useTaskRefresh();
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  const candidates = $api.useQuery("get", "/api/v1/tasks/", {
    params: { query: { search: search || undefined, page_size: 8, open: true } },
  }, { enabled: adding });
  const add = $api.useMutation("post", "/api/v1/tasks/{task_id}/dependencies/", {
    onSuccess: () => { refresh(); setAdding(false); setSearch(""); toast.success("Dependency added"); },
  });
  const remove = $api.useMutation("delete", "/api/v1/tasks/{task_id}/dependencies/{dependency_id}/", { onSuccess: refresh });
  const editable = !task.is_read_only;
  return (
    <Card>
      <CardHeader title="Subtasks & dependencies" action={
        <div className="flex gap-2">
          {can("task.create") && editable && <Button variant="outline" size="sm" onClick={onNewSubtask}><GitBranch /> Subtask</Button>}
          {can("task.dependency.manage") && editable && <Button variant="outline" size="sm" onClick={() => setAdding(true)}><Link2 /> Depends on</Button>}
        </div>
      } />
      <div className="grid gap-5 p-5 md:grid-cols-2">
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Subtasks</h3>
          {task.subtasks.length === 0 ? <p className="text-sm text-muted">None</p> : (
            <ul className="flex flex-col gap-1.5">
              {task.subtasks.map((s) => (
                <li key={s.id}>
                  <Link href={`/tasks/${s.id}`} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-hover">
                    <span className="min-w-0 truncate text-sm"><span className="font-mono text-xs text-muted">{s.key}</span> {s.title}</span>
                    <StatusBadge status={s.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Waiting on</h3>
          {task.dependencies.length === 0 ? <p className="text-sm text-muted">Nothing</p> : (
            <ul className="flex flex-col gap-1.5">
              {task.dependencies.map((d) => (
                <li key={d.id} className="flex items-center gap-2">
                  <Link href={`/tasks/${d.blocked_by.id}`} className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-lg px-2 py-1.5 hover:bg-hover">
                    <span className="min-w-0 truncate text-sm"><span className="font-mono text-xs text-muted">{d.blocked_by.key}</span> {d.blocked_by.title}</span>
                    <StatusBadge status={d.blocked_by.status} />
                  </Link>
                  {can("task.dependency.manage") && editable && (
                    <Button variant="ghost" size="sm" aria-label={`Remove dependency on ${d.blocked_by.key}`}
                            onClick={() => remove.mutate({ params: { path: { task_id: task.id, dependency_id: d.id } } })}><Trash2 /></Button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {task.dependents.length > 0 && (
            <>
              <h3 className="mt-4 mb-2 text-xs font-bold uppercase tracking-wide text-muted">Blocking</h3>
              <ul className="flex flex-col gap-1.5">
                {task.dependents.map((d) => (
                  <li key={d.id}><Link href={`/tasks/${d.id}`} className="text-sm hover:underline"><span className="font-mono text-xs text-muted">{d.key}</span> {d.title}</Link></li>
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent title={`${task.key} depends on…`} description="It cannot start until the chosen task is completed or cancelled.">
          <Input aria-label="Search tasks" placeholder="Search tasks" value={search} onChange={(e) => setSearch(e.target.value)} />
          <ul className="mt-3 max-h-72 divide-y divide-line overflow-y-auto rounded-xl border border-line">
            {(candidates.data?.results ?? []).filter((t) => t.id !== task.id).map((t) => (
              <li key={t.id}>
                <button type="button" className="flex min-h-11 w-full items-center justify-between gap-2 px-3 text-left hover:bg-hover"
                        onClick={() => add.mutate({ params: { path: { task_id: task.id } }, body: { blocked_by_id: t.id } })}>
                  <span className="min-w-0 truncate text-sm"><span className="font-mono text-xs text-muted">{t.key}</span> {t.title}</span>
                  <StatusBadge status={t.status!} />
                </button>
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* ----------------------------------------------------------------- Comments */

const MENTION = /@\[([^\]\n]{1,100})\]\(user:[0-9a-fA-F-]{36}\)/g;

/** Plain text with mentions highlighted. No HTML is ever interpreted. */
export function CommentBody({ body }: { body: string }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of body.matchAll(MENTION)) {
    parts.push(body.slice(last, m.index));
    parts.push(<span key={m.index} className="rounded bg-primary-100 px-1 font-semibold text-primary-700">@{m[1]}</span>);
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(body.slice(last));
  return <p className="whitespace-pre-wrap break-words text-sm text-ink">{parts}</p>;
}

export function CommentsPanel({ task }: { task: TaskDetail }) {
  const me = useMe();
  const { can } = useSession();
  const refresh = useTaskRefresh();
  const comments = $api.useQuery("get", "/api/v1/tasks/{task_id}/comments/", { params: { path: { task_id: task.id }, query: { page_size: 100 } } });
  const [body, setBody] = useState("");
  const [mentioning, setMentioning] = useState(false);
  const [picked, setPicked] = useState<Person[]>([]);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const post = $api.useMutation("post", "/api/v1/tasks/{task_id}/comments/", { onSuccess: () => { refresh(); setBody(""); } });
  const remove = $api.useMutation("delete", "/api/v1/tasks/{task_id}/comments/{comment_id}/", { onSuccess: refresh });
  const canComment = can("task.comment") && !task.is_read_only;
  const insertMention = (p: Person) => {
    const token = `@[${p.full_name}](user:${p.id}) `;
    setBody((b) => `${b}${b && !b.endsWith(" ") ? " " : ""}${token}`);
    setMentioning(false);
    setPicked([]);
    textRef.current?.focus();
  };
  const list = [...(comments.data?.results ?? [])].reverse();
  return (
    <Card>
      <CardHeader title="Comments" description="Mention people to notify them." />
      <div className="flex flex-col gap-4 p-5">
        <QueryState query={comments} rows={2} isEmpty={() => list.length === 0}
                    empty={<EmptyState icon={<MessageSquare className="size-6" />} title="No comments yet" />}>
          {() => (
            <ul className="flex flex-col gap-4">
              {list.map((c) => (
                <li key={c.id} className={cn("flex gap-3", c.kind !== "COMMENT" && "rounded-xl bg-surface-2 p-3")}>
                  <Avatar name={c.author?.full_name ?? "System"} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">
                      <span className="font-semibold text-ink">{c.author?.full_name ?? "System"}</span>
                      <span className="ml-2 text-xs text-muted">{timeAgo(c.created_at)}{c.edited_at && " · edited"}</span>
                      {c.kind !== "COMMENT" && <Badge className="ml-2" tone={c.kind === "REVIEW" ? "info" : "neutral"}>{titleCase(c.kind ?? "")}</Badge>}
                    </p>
                    {c.is_deleted ? <p className="text-sm italic text-muted">Comment deleted</p> : <CommentBody body={c.body} />}
                  </div>
                  {!c.is_deleted && c.kind === "COMMENT" && (c.author?.id === me.id || can("task.update")) && !task.is_read_only && (
                    <Button variant="ghost" size="sm" aria-label="Delete comment"
                            onClick={() => remove.mutate({ params: { path: { task_id: task.id, comment_id: c.id } } })}><Trash2 /></Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </QueryState>
        {canComment && (
          <form onSubmit={(e) => { e.preventDefault(); if (body.trim()) post.mutate({ params: { path: { task_id: task.id } }, body: { body } }); }}
                className="flex flex-col gap-2 border-t border-line pt-4">
            <label htmlFor="new-comment" className="sr-only">Write a comment</label>
            <Textarea id="new-comment" ref={textRef} placeholder="Write a comment…" value={body} onChange={(e) => setBody(e.target.value)} />
            <div className="flex flex-wrap justify-between gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setMentioning(true)}><AtSign /> Mention</Button>
              <Button type="submit" size="sm" loading={post.isPending} disabled={!body.trim()}>Comment</Button>
            </div>
          </form>
        )}
      </div>
      <Dialog open={mentioning} onOpenChange={setMentioning}>
        <DialogContent title="Mention someone" description="Only people who can see this task can be mentioned.">
          <PeoplePicker single label="Person" value={picked} onChange={(p) => p[0] && insertMention(p[0])} />
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* ----------------------------------------------------------------- Attachments */

export function AttachmentsPanel({ task }: { task: TaskDetail }) {
  const me = useMe();
  const { can } = useSession();
  const refresh = useTaskRefresh();
  const files = $api.useQuery("get", "/api/v1/tasks/{task_id}/attachments/", { params: { path: { task_id: task.id } } });
  const remove = $api.useMutation("delete", "/api/v1/tasks/{task_id}/attachments/{attachment_id}/", { onSuccess: refresh });
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const canUpload = can("task.attachment.upload") && !task.is_read_only;
  const onFiles = async (list: FileList | null) => {
    if (!list?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(list)) {
        await uploadFile(`/api/v1/tasks/${task.id}/attachments/`, file);
        toast.success(`${file.name} uploaded`);
      }
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setUploading(false);
      refresh();
      if (input.current) input.current.value = "";
    }
  };
  return (
    <Card>
      <CardHeader title="Files" description="Images, PDF, Office files, text and ZIP up to 25 MB."
                  action={canUpload && (
                    <>
                      <input ref={input} type="file" multiple className="sr-only" id="task-file" onChange={(e) => void onFiles(e.target.files)}
                             accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.log,.csv,.md,.json,.docx,.xlsx,.pptx,.zip" />
                      <Button variant="outline" size="sm" loading={uploading} onClick={() => input.current?.click()}><FileUp /> Upload</Button>
                    </>
                  )} />
      <QueryState query={files} rows={2} isEmpty={(d) => !d.length}
                  empty={<EmptyState icon={<Paperclip className="size-6" />} title="No files" />}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.map((f) => (
              <li key={f.id} className="flex items-center gap-3 px-5 py-3">
                <Paperclip className="size-4 text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{f.filename}</p>
                  <p className="text-xs text-muted">{formatBytes(f.size_bytes)} · {f.uploaded_by?.full_name ?? "—"} · {timeAgo(f.created_at)}</p>
                </div>
                <Button variant="ghost" size="sm" aria-label={`Download ${f.filename}`}
                        onClick={() => void downloadFile(`/api/v1/tasks/${task.id}/attachments/${f.id}/download/`, f.filename).catch((e) => toast.error(errorMessage(e)))}>
                  <Download />
                </Button>
                {!task.is_read_only && (f.uploaded_by?.id === me.id || can("task.attachment.delete")) && (
                  <Button variant="ghost" size="sm" aria-label={`Delete ${f.filename}`}
                          onClick={() => remove.mutate({ params: { path: { task_id: task.id, attachment_id: f.id } } })}><Trash2 /></Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Card>
  );
}

/* ----------------------------------------------------------------- Review */

export function ReviewPanel({ task }: { task: TaskDetail }) {
  const me = useMe();
  const { can, scopeOf } = useSession();
  const refresh = useTaskRefresh();
  const history = $api.useQuery("get", "/api/v1/tasks/{task_id}/reviews/", { params: { path: { task_id: task.id } } });
  const [deciding, setDeciding] = useState<"approve" | "changes" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const path = { params: { path: { task_id: task.id } } };
  const done = (msg: string) => () => { refresh(); setDeciding(null); setSubmitting(false); toast.success(msg); };
  const submit = $api.useMutation("post", "/api/v1/tasks/{task_id}/review/submit/", { onSuccess: done("Submitted for review") });
  const approve = $api.useMutation("post", "/api/v1/tasks/{task_id}/review/approve/", { onSuccess: done("Approved: task completed") });
  const changes = $api.useMutation("post", "/api/v1/tasks/{task_id}/review/request-changes/", { onSuccess: done("Changes requested") });
  const rounds = history.data ?? [];
  const pending = rounds.find((r) => r.decision === "PENDING");
  const isAssignee = task.assignees.some((a) => a.user.id === me.id);
  const reviewerId = pending?.reviewer.id ?? task.reviewer?.id ?? task.created_by.id;
  const canDecide = Boolean(pending) && can("review.decide") && (reviewerId === me.id || scopeOf("review.decide").includes("COMPANY"));
  const openRequired = task.checklists.flatMap((c) => c.items).filter((i) => i.is_required && !i.is_done).length;
  return (
    <Card>
      <CardHeader title="Review" description={`Reviewer: ${pending?.reviewer.full_name ?? task.reviewer?.full_name ?? task.created_by.full_name}`} />
      <div className="flex flex-col gap-4 p-5">
        {task.status === "IN_PROGRESS" && isAssignee && can("review.submit") && (
          <div className="rounded-xl bg-primary-50 p-3">
            {openRequired > 0 ? (
              <p className="text-sm text-warning">{openRequired} required checklist item(s) must be done before submitting.</p>
            ) : (
              <Button className="w-full" onClick={() => setSubmitting(true)}><CheckCircle2 /> Submit for review</Button>
            )}
          </div>
        )}
        {canDecide && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Button onClick={() => setDeciding("approve")}><CheckCircle2 /> Approve</Button>
            <Button variant="outline" onClick={() => setDeciding("changes")}><XCircle /> Request changes</Button>
          </div>
        )}
        <QueryState query={history} rows={1} isEmpty={(d) => !d.length} empty={<p className="text-sm text-muted">Not submitted yet.</p>}>
          {(items) => (
            <ol className="flex flex-col gap-3">
              {[...items].reverse().map((r) => (
                <li key={r.id} className="rounded-xl border border-line p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-bold text-ink">Round {r.round}</span>
                    <Badge tone={r.decision === "APPROVED" ? "success" : r.decision === "PENDING" ? "warning" : "danger"}>{titleCase(r.decision ?? "")}</Badge>
                  </div>
                  <p className="mt-1 text-muted">Submitted by {r.submitted_by.full_name} · {formatDateTime(r.submitted_at)}</p>
                  {r.submission_note && <p className="mt-1 whitespace-pre-wrap text-ink">“{r.submission_note}”</p>}
                  {r.decided_at && (
                    <p className="mt-2 text-muted">{r.decided_by?.full_name} · {formatDateTime(r.decided_at)}</p>
                  )}
                  {r.comment && <p className="mt-1 whitespace-pre-wrap rounded-lg bg-surface-2 p-2 text-ink">{r.comment}</p>}
                </li>
              ))}
            </ol>
          )}
        </QueryState>
      </div>
      <ConfirmDialog open={submitting} onOpenChange={setSubmitting} title="Submit for review"
                     description="Running timers on this task stop. The task is frozen until the reviewer decides."
                     reasonLabel="Note for the reviewer (optional)" confirmLabel="Submit" loading={submit.isPending}
                     onConfirm={(note) => submit.mutate({ ...path, body: { note } })} />
      <ConfirmDialog open={deciding === "approve"} onOpenChange={() => setDeciding(null)} title={`Approve ${task.key}?`}
                     description="The task becomes COMPLETED and read-only." reasonLabel="Comment (optional)"
                     confirmLabel="Approve" loading={approve.isPending}
                     onConfirm={(comment) => approve.mutate({ ...path, body: { comment } })} />
      <ConfirmDialog open={deciding === "changes"} onOpenChange={() => setDeciding(null)} title="Request changes"
                     description="The task goes back to IN_PROGRESS." reasonLabel="What needs to change?" reasonRequired
                     confirmLabel="Request changes" danger loading={changes.isPending}
                     onConfirm={(comment) => changes.mutate({ ...path, body: { comment } })} />
    </Card>
  );
}

/* ----------------------------------------------------------------- Time log */

export function TimeLogPanel({ task }: { task: TaskDetail }) {
  const me = useMe();
  const refresh = useTaskRefresh();
  const entries = $api.useQuery("get", "/api/v1/tasks/{task_id}/time-entries/", { params: { path: { task_id: task.id } } });
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState("");
  const [minutes, setMinutes] = useState("60");
  const [note, setNote] = useState("");
  const log = $api.useMutation("post", "/api/v1/time/entries/", {
    onSuccess: () => { refresh(); setOpen(false); setNote(""); toast.success("Time logged"); },
  });
  const isAssignee = task.assignees.some((a) => a.user.id === me.id);
  const total = (entries.data ?? []).reduce((s, e) => s + (e.duration_seconds ?? 0), 0);
  return (
    <Card>
      <CardHeader title="Time" description={`${formatDuration(total)} logged${task.estimated_minutes ? ` of ${formatDuration(task.estimated_minutes * 60)} estimated` : ""}`}
                  action={isAssignee && !task.is_read_only && <Button variant="outline" size="sm" onClick={() => setOpen(true)}><Plus /> Log time</Button>} />
      <QueryState query={entries} rows={2} isEmpty={(d) => !d.length} empty={<p className="px-5 py-4 text-sm text-muted">No time logged yet.</p>}>
        {(items) => (
          <ul className="divide-y divide-line">
            {items.slice(0, 12).map((e) => (
              <li key={e.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                <Avatar name={e.user.full_name} className="size-7" />
                <span className="min-w-0 flex-1 truncate">{e.user.full_name}{e.note && <span className="text-muted"> · {e.note}</span>}</span>
                <span className="text-xs text-muted">{e.work_date}</span>
                <span className="w-16 text-right font-semibold tabular-nums">{e.ended_at ? formatDuration(e.duration_seconds) : "running"}</span>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Log time manually" description="Entries cannot overlap your other time or be in the future.">
          <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => {
            e.preventDefault();
            const started = new Date(start);
            const ended = new Date(started.getTime() + Number(minutes) * 60_000);
            log.mutate({ body: { task_id: task.id, started_at: started.toISOString(), ended_at: ended.toISOString(), note } });
          }}>
            <Field label="Started at" htmlFor="log-start"><Input type="datetime-local" required value={start} onChange={(e) => setStart(e.target.value)} /></Field>
            <Field label="Minutes" htmlFor="log-min"><Input type="number" min={1} max={1440} required value={minutes} onChange={(e) => setMinutes(e.target.value)} /></Field>
            <Field label="Note" htmlFor="log-note" className="sm:col-span-2"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <div className="sm:col-span-2">
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
                <Button type="submit" loading={log.isPending}>Log time</Button>
              </DialogFooter>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* ----------------------------------------------------------------- Activity */

const VERB: Record<string, string> = {
  created: "created the task", updated: "edited the task", assigned: "assigned people", unassigned: "removed an assignee",
  status_changed: "changed the status", commented: "commented", acknowledged: "acknowledged the assignment",
  checklist_added: "added a checklist", checklist_removed: "removed a checklist", checklist_item_done: "ticked an item",
  checklist_item_undone: "unticked an item", dependency_added: "added a dependency", dependency_removed: "removed a dependency",
  attachment_added: "uploaded a file", attachment_removed: "removed a file", escalated: "escalated to managers",
  review_submitted: "submitted for review", review_approved: "approved the work", review_changes_requested: "requested changes",
  time_logged: "logged time", deleted: "deleted the task", restored: "restored the task",
};

export function ActivityPanel({ taskId }: { taskId: string }) {
  const activity = $api.useQuery("get", "/api/v1/tasks/{task_id}/activity/", { params: { path: { task_id: taskId }, query: { page_size: 50 } } });
  return (
    <Card>
      <CardHeader title="Activity" />
      <QueryState query={activity} rows={3}>
        {(data) => (
          <ol className="relative flex flex-col gap-4 p-5 before:absolute before:top-6 before:bottom-6 before:left-[34px] before:w-px before:bg-line">
            {data.results.map((a) => {
              const d = a.data as Record<string, string>;
              return (
                <li key={a.id} className="relative flex gap-3 text-sm">
                  <span className="z-[1] mt-1 size-3 shrink-0 rounded-full border-2 border-primary-500 bg-surface ml-[6px]" aria-hidden />
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-1.5">
                      <span className="font-semibold text-ink">{a.actor?.full_name ?? "System"}</span>
                      {a.verb === "status_changed" && d.to ? (
                        <>
                          moved
                          {d.from && <><StatusBadge status={d.from as never} /><span aria-hidden>→</span></>}
                          <StatusBadge status={d.to as never} />
                          <span className="text-muted">·</span>
                          <span className="text-muted" title={formatDateTime(a.created_at)}>{timeAgo(a.created_at)}</span>
                        </>
                      ) : (
                        VERB[a.verb] ?? a.verb
                      )}
                    </p>
                    {d.comment && <p className="text-muted">“{d.comment}”</p>}
                    {!(a.verb === "status_changed" && d.to) && <p className="text-xs text-muted">{formatDateTime(a.created_at)}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </QueryState>
    </Card>
  );
}
