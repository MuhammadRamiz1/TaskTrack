"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell, LogOut, MonitorSmartphone, ShieldCheck, User } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from "@/components/ui/overlay";
import { Avatar } from "@/components/ui/primitives";
import { $api } from "@/lib/api/client";
import { useMe, useSession } from "@/lib/auth/session";
import { cn, timeAgo } from "@/lib/utils";

export function NotificationBell() {
  const { user } = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const enabled = Boolean(user?.company);
  const count = $api.useQuery("get", "/api/v1/notifications/unread-count/", undefined, {
    enabled,
    refetchInterval: 30_000,
  });
  const latest = $api.useQuery("get", "/api/v1/notifications/", { params: { query: { unread: true } } }, {
    enabled,
  });
  const markRead = $api.useMutation("post", "/api/v1/notifications/{notification_id}/read/", {
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["get", "/api/v1/notifications/unread-count/"] }),
  });
  if (!enabled) return null;
  const unread = count.data?.unread ?? 0;
  const items = latest.data?.results?.slice(0, 6) ?? [];
  return (
    <Dropdown onOpenChange={(open) => open && void latest.refetch()}>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications, ${unread} unread`} className="relative">
          <Bell />
          {unread > 0 && (
            <span className="absolute top-1.5 right-1.5 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold text-white dark:text-[#2a0d10]">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </DropdownTrigger>
      <DropdownContent className="w-[min(92vw,360px)]">
        <DropdownLabel>Unread notifications</DropdownLabel>
        {items.length === 0 && <p className="px-2.5 py-4 text-sm text-muted">You are all caught up.</p>}
        {items.map((n) => (
          <DropdownItem
            key={n.id}
            className="flex-col items-start gap-0.5 py-2"
            onSelect={() => {
              markRead.mutate({ params: { path: { notification_id: n.id } } });
              if (n.entity_type === "task" && n.entity_id) router.push(`/tasks/${n.entity_id}`);
              else if (n.entity_type === "timesheet" && n.entity_id) router.push(`/timesheets/${n.entity_id}`);
            }}
          >
            <span className="line-clamp-2 font-semibold">{n.title}</span>
            <span className="text-xs text-muted">{timeAgo(n.created_at)}</span>
          </DropdownItem>
        ))}
        <DropdownSeparator />
        <DropdownItem asChild>
          <Link href="/notifications" className="justify-center text-link">
            See all notifications
          </Link>
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}

export function UserMenu() {
  const me = useMe();
  const { logout } = useSession();
  const roles = me.roles.map((r) => r.name).join(", ");
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <button
          className="flex items-center gap-2 rounded-xl p-1 pr-2 hover:bg-hover"
          aria-label={`Account menu for ${me.full_name}`}
        >
          <Avatar name={me.full_name} />
          <span className="hidden max-w-36 truncate text-sm font-semibold text-ink lg:inline">{me.first_name}</span>
        </button>
      </DropdownTrigger>
      <DropdownContent className="w-64">
        <div className="px-2.5 py-2">
          <p className="truncate font-semibold text-ink">{me.full_name}</p>
          <p className="truncate text-xs text-muted">{me.email}</p>
          <p className={cn("mt-1 truncate text-xs font-semibold text-primary-700")}>{roles}</p>
        </div>
        <DropdownSeparator />
        <DropdownItem asChild>
          <Link href="/settings">
            <User /> Profile
          </Link>
        </DropdownItem>
        <DropdownItem asChild>
          <Link href="/settings/security">
            <ShieldCheck /> Security
          </Link>
        </DropdownItem>
        <DropdownSeparator />
        <DropdownItem onSelect={() => void logout(true)}>
          <MonitorSmartphone /> Sign out everywhere
        </DropdownItem>
        <DropdownItem danger onSelect={() => void logout()}>
          <LogOut /> Sign out
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}
