"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { $api } from "@/lib/api/client";
import { ApiError, applyFieldErrors } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useSession } from "@/lib/auth/session";

import { PRIORITIES, type TaskPriority } from "./meta";

type Task = components["schemas"]["TaskDetail"];
type Values = {
  project_id: string;
  title: string;
  description: string;
  instructions: string;
  acceptance_criteria: string;
  priority: TaskPriority;
  start_date: string;
  due_date: string;
  estimated_hours: string;
};

const FIELDS = ["title", "description", "instructions", "acceptance_criteria", "priority", "start_date", "due_date"] as const;

export function TaskFormDialog({
  task,
  parent,
  defaultProjectId,
  onClose,
}: {
  task?: Task;
  parent?: { id: string; key: string };
  defaultProjectId?: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const { can } = useSession();
  const editing = Boolean(task);
  const projects = $api.useQuery("get", "/api/v1/org/projects/", { params: { query: { page_size: 100, status: ["ACTIVE"] } } });
  const form = useForm<Values>({
    defaultValues: task
      ? {
          project_id: task.project.id,
          title: task.title,
          description: task.description ?? "",
          instructions: task.instructions ?? "",
          acceptance_criteria: task.acceptance_criteria ?? "",
          priority: task.priority ?? "MEDIUM",
          start_date: task.start_date ?? "",
          due_date: task.due_date ?? "",
          estimated_hours: task.estimated_minutes ? String(task.estimated_minutes / 60) : "",
        }
      : {
          project_id: defaultProjectId ?? "",
          title: "",
          description: "",
          instructions: "",
          acceptance_criteria: "",
          priority: "MEDIUM",
          start_date: "",
          due_date: "",
          estimated_hours: "",
        },
  });
  const [assignees, setAssignees] = useState<Person[]>([]);
  const [reviewer, setReviewer] = useState<Person[]>(task?.reviewer ? [task.reviewer] : []);
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/{task_id}/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/{task_id}/subtasks/"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/tasks/board/"] });
  };
  const onError = (e: unknown) => {
    if (!applyFieldErrors(e, form.setError, [...FIELDS, "project_id"]) && e instanceof ApiError && e.code === "version_conflict") {
      toast.error("Someone else changed this task. Reload to see their changes.");
    }
  };
  const create = $api.useMutation("post", "/api/v1/tasks/", {
    onSuccess: (t) => { invalidate(); toast.success(`${t.key} created`); onClose(); router.push(`/tasks/${t.id}`); },
    onError,
  });
  const createSub = $api.useMutation("post", "/api/v1/tasks/{task_id}/subtasks/", {
    onSuccess: (t) => { invalidate(); toast.success(`${t.key} created`); onClose(); },
    onError,
  });
  const update = $api.useMutation("patch", "/api/v1/tasks/{task_id}/", {
    onSuccess: () => { invalidate(); toast.success("Task saved"); onClose(); },
    onError,
  });

  const submit = form.handleSubmit((v) => {
    const common = {
      title: v.title,
      description: v.description,
      instructions: v.instructions,
      acceptance_criteria: v.acceptance_criteria,
      priority: v.priority,
      start_date: v.start_date || null,
      due_date: v.due_date || null,
      estimated_minutes: v.estimated_hours ? Math.round(Number(v.estimated_hours) * 60) : null,
      reviewer_id: reviewer[0]?.id ?? null,
    };
    if (task) {
      update.mutate({ params: { path: { task_id: task.id } }, body: { ...common, version: task.version } });
    } else if (parent) {
      createSub.mutate({
        params: { path: { task_id: parent.id } },
        body: { ...common, project_id: v.project_id, assignee_ids: assignees.map((a) => a.id) },
      });
    } else {
      create.mutate({ body: { ...common, project_id: v.project_id, assignee_ids: assignees.map((a) => a.id) } });
    }
  });
  const { errors } = form.formState;
  const title = editing ? `Edit ${task!.key}` : parent ? `New subtask of ${parent.key}` : "New task";

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={title}>
        <form className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={submit}>
          {!editing && !parent && (
            <Field label="Project" htmlFor="project_id" error={errors.project_id?.message} required className="sm:col-span-2">
              <Select {...form.register("project_id", { required: "Choose a project" })}>
                <option value="">Choose…</option>
                {(projects.data?.results ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.key} · {p.name}</option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Title" htmlFor="title" error={errors.title?.message} required className="sm:col-span-2">
            <Input {...form.register("title", { required: "Give the task a title", maxLength: 300 })} />
          </Field>
          <Field label="Description" htmlFor="description" className="sm:col-span-2">
            <Textarea rows={4} {...form.register("description")} />
          </Field>
          <Field label="Instructions" htmlFor="instructions" hint="How to do it: steps, links, constraints">
            <Textarea {...form.register("instructions")} />
          </Field>
          <Field label="Acceptance criteria" htmlFor="acceptance_criteria" hint="What 'done' means; the reviewer checks this">
            <Textarea {...form.register("acceptance_criteria")} />
          </Field>
          <Field label="Priority" htmlFor="priority" hint={can("task.set_priority") ? undefined : "Needs priority permission to change"}>
            <Select disabled={!can("task.set_priority")} {...form.register("priority")}>
              {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </Select>
          </Field>
          <Field label="Estimate (hours)" htmlFor="estimated_hours">
            <Input type="number" min={0} step={0.25} inputMode="decimal" {...form.register("estimated_hours")} />
          </Field>
          <Field label="Start date" htmlFor="start_date" error={errors.start_date?.message}>
            <Input type="date" {...form.register("start_date")} />
          </Field>
          <Field label="Due date" htmlFor="due_date" error={errors.due_date?.message}>
            <Input type="date" {...form.register("due_date")} />
          </Field>
          <div className="sm:col-span-2">
            <p className="mb-1.5 text-sm font-semibold text-ink">Reviewer</p>
            <p className="mb-2 text-xs text-muted">Approves the work. Defaults to the task creator.</p>
            <PeoplePicker single label="Reviewer" value={reviewer} onChange={setReviewer} />
          </div>
          {!editing && can("task.assign") && (
            <div className="sm:col-span-2">
              <p className="mb-1.5 text-sm font-semibold text-ink">Assignees</p>
              <PeoplePicker label="Assignees" value={assignees} onChange={setAssignees} />
            </div>
          )}
          <div className="sm:col-span-2">
            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={create.isPending || update.isPending || createSub.isPending}>
                {editing ? "Save changes" : "Create task"}
              </Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
