"use client";

import { CalendarDays, Columns3, List, Plus, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Pager } from "@/components/common/pager";
import { Can } from "@/components/layout/guards";
import { STATUSES, PRIORITIES } from "@/components/tasks/meta";
import { TaskFormDialog } from "@/components/tasks/task-form";
import { TaskBoard, TaskCalendar, TaskTable } from "@/components/tasks/task-views";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { Card, Checkbox, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, PageHeader, QueryState } from "@/components/ui/states";
import { $api } from "@/lib/api/client";
import { cleanParams } from "@/lib/utils";

const PAGE_SIZE = 25;

function TasksScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const view = params.get("view") ?? "board";
  const [page, setPage] = useState(1);
  const [search, rawSetSearch] = useState(params.get("search") ?? "");
  const [project, rawSetProject] = useState(params.get("project") ?? "");
  const [status, rawSetStatus] = useState(params.get("status") ?? "");
  const [priority, rawSetPriority] = useState("");
  const [overdue, rawSetOverdue] = useState(params.get("overdue") === "true");
  const [reassign, rawSetReassign] = useState(false);
  // Any filter change goes back to the first page.
  const resetting = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(1); };
  const setSearch = resetting(rawSetSearch);
  const setProject = resetting(rawSetProject);
  const setStatus = resetting(rawSetStatus);
  const setPriority = resetting(rawSetPriority);
  const setOverdue = resetting(rawSetOverdue);
  const setReassign = resetting(rawSetReassign);
  const [creating, setCreating] = useState(false);
  const [month, setMonth] = useState(() => new Date());

  const projects = $api.useQuery("get", "/api/v1/org/projects/", { params: { query: { page_size: 100 } } });
  const projectList = projects.data?.results ?? [];
  const boardProject = project || projectList[0]?.id || "";

  const tasks = $api.useQuery("get", "/api/v1/tasks/", {
    params: {
      query: cleanParams({
        page, page_size: PAGE_SIZE, search, project,
        status: status === "open" ? undefined : status ? [status as "ASSIGNED"] : undefined,
        open: status === "open" ? true : undefined,
        priority: priority ? [priority as "HIGH"] : undefined,
        overdue: overdue || undefined,
        needs_reassignment: reassign || undefined,
        ordering: "-priority_rank",
      }),
    },
  }, { enabled: view === "list" });

  const setView = (v: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("view", v);
    router.replace(`/tasks?${next.toString()}`);
  };

  return (
    <>
      <PageHeader title="Tasks" description="Everything you can see across your projects."
                  actions={<Can anyOf={["task.create"]}><Button onClick={() => setCreating(true)}><Plus /> New task</Button></Can>} />
      <Tabs value={view} onValueChange={setView}>
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <TabsList>
            <TabsTrigger value="list"><List /> List</TabsTrigger>
            <TabsTrigger value="board"><Columns3 /> Board</TabsTrigger>
            <TabsTrigger value="calendar"><CalendarDays /> Calendar</TabsTrigger>
          </TabsList>
          <Select aria-label="Project" className="lg:w-64" value={view === "board" ? boardProject : project}
                  onChange={(e) => setProject(e.target.value)}>
            {view !== "board" && <option value="">All projects</option>}
            {projectList.map((p) => <option key={p.id} value={p.id}>{p.key} · {p.name}</option>)}
          </Select>
        </div>

        <TabsContent value="list">
          <Card>
            <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-2 lg:grid-cols-[1fr_180px_160px_auto_auto] lg:items-center">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-placeholder" />
                <Input aria-label="Search tasks" placeholder="Search title or description" className="pl-9"
                       value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
              <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Any status</option>
                <option value="open">Open (not done)</option>
                {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </Select>
              <Select aria-label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
                <option value="">Any priority</option>
                {PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </Select>
              <label className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Checkbox checked={overdue} onCheckedChange={(v) => setOverdue(v === true)} /> Overdue
              </label>
              <label className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Checkbox checked={reassign} onCheckedChange={(v) => setReassign(v === true)} /> Needs reassignment
              </label>
            </div>
            <QueryState query={tasks} isEmpty={(d) => !d.results.length}
                        empty={<EmptyState title="No tasks match" description="Try clearing a filter." />}>
              {(data) => (
                <>
                  <TaskTable tasks={data.results} />
                  <Pager page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} />
                </>
              )}
            </QueryState>
          </Card>
        </TabsContent>
        <TabsContent value="board">
          {boardProject ? <TaskBoard projectId={boardProject} /> : <EmptyState title="No projects yet" />}
        </TabsContent>
        <TabsContent value="calendar">
          <TaskCalendar month={month} onMonth={setMonth} />
        </TabsContent>
      </Tabs>
      {creating && <TaskFormDialog defaultProjectId={project || undefined} onClose={() => setCreating(false)} />}
    </>
  );
}

export default function TasksPage() {
  return (
    <Suspense>
      <TasksScreen />
    </Suspense>
  );
}
