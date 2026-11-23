"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Settings } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, Tabs, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/states";
import { $api, api } from "@/lib/api/client";
import { cn, timeAgo } from "@/lib/utils";

export default function NotificationsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [unread, setUnread] = useState(false);
  const feed = useInfiniteQuery({
    queryKey: ["notifications-feed", unread],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      (await api.GET("/api/v1/notifications/", { params: { query: { unread: unread || undefined, cursor: pageParam, page_size: 30 } } })).data!,
    getNextPageParam: (last) => (last.next ? new URL(last.next, location.origin).searchParams.get("cursor") ?? undefined : undefined),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["notifications-feed"] });
    void qc.invalidateQueries({ queryKey: ["get", "/api/v1/notifications/unread-count/"] });
  };
  const markAll = $api.useMutation("post", "/api/v1/notifications/read-all/", { onSuccess: refresh });
  const markOne = $api.useMutation("post", "/api/v1/notifications/{notification_id}/read/", { onSuccess: refresh });
  const items = feed.data?.pages.flatMap((p) => p.results) ?? [];
  return (
    <>
      <PageHeader title="Notifications" actions={
        <>
          <Button variant="outline" asChild><Link href="/settings/notifications"><Settings /> Settings</Link></Button>
          <Button variant="outline" loading={markAll.isPending} onClick={() => markAll.mutate({})}><CheckCheck /> Mark all read</Button>
        </>
      } />
      <Tabs value={unread ? "unread" : "all"} onValueChange={(v) => setUnread(v === "unread")}>
        <TabsList className="mb-4"><TabsTrigger value="all">All</TabsTrigger><TabsTrigger value="unread">Unread</TabsTrigger></TabsList>
      </Tabs>
      <Card>
        {feed.isPending ? <LoadingRows /> : feed.error ? <ErrorState error={feed.error} onRetry={() => feed.refetch()} /> :
          items.length === 0 ? <EmptyState icon={<Bell className="size-6" />} title="You're all caught up" /> : (
          <ul className="divide-y divide-line">
            {items.map((n) => (
              <li key={n.id}>
                <button type="button" className={cn("flex w-full items-start gap-3 px-5 py-3.5 text-left hover:bg-hover", !n.is_read && "bg-primary-50")}
                        onClick={() => {
                          if (!n.is_read) markOne.mutate({ params: { path: { notification_id: n.id } } });
                          if (n.entity_type === "task" && n.entity_id) router.push(`/tasks/${n.entity_id}`);
                          else if (n.entity_type === "timesheet" && n.entity_id) router.push(`/timesheets/${n.entity_id}`);
                          else if (n.entity_type === "reportexport") router.push("/reports");
                        }}>
                  <span className={cn("mt-1.5 size-2.5 shrink-0 rounded-full", n.is_read ? "bg-transparent" : "bg-primary-600")} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold text-ink">{n.title}</span>
                    {n.body && <span className="line-clamp-2 block text-sm text-muted">{n.body}</span>}
                    <span className="block text-xs text-muted">{timeAgo(n.created_at)}{!n.is_read && <span className="sr-only">, unread</span>}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {feed.hasNextPage && (
          <div className="border-t border-line p-4 text-center">
            <Button variant="outline" loading={feed.isFetchingNextPage} onClick={() => void feed.fetchNextPage()}>Load more</Button>
          </div>
        )}
      </Card>
    </>
  );
}
