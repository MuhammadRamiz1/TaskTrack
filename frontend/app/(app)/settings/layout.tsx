"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { PageHeader } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { canAny, user } = useSession();
  const tabs = [
    { href: "/settings", label: "Profile" },
    { href: "/settings/security", label: "Security" },
    ...(user?.company ? [{ href: "/settings/notifications", label: "Notifications" }] : []),
    ...(canAny("company.settings.manage", "role.manage", "workflow.manage")
      ? [{ href: "/settings/company", label: "Company" }]
      : []),
  ];
  return (
    <div>
      <PageHeader title="Settings" description="Your profile, security and preferences." />
      <nav aria-label="Settings sections" className="mb-5 flex gap-1 overflow-x-auto rounded-xl bg-surface-2 p-1">
        {tabs.map((t) => {
          const active = pathname === t.href;
          return (
            <Link
              key={t.href}
              href={t.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-9 items-center whitespace-nowrap rounded-lg px-3 text-sm font-semibold",
                active ? "bg-surface text-primary-700 shadow-sm" : "text-muted hover:text-ink",
              )}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
