import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/layout/theme-toggle";

import TaskIllustration from "./task-illustration";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="grid size-9 place-items-center rounded-[11px] bg-linear-to-br from-primary-400 to-primary-600 text-white shadow-button">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden>
          <path d="M5 12.5l4 4L19 7" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {!compact && <span className="text-[19px] font-extrabold tracking-tight text-ink">TaskTrack</span>}
    </span>
  );
}

/** Two-column card for sign-in, invite, and password pages (illustration on desktop only). */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <main
      id="main"
      className="flex min-h-dvh items-center justify-center bg-page bg-[radial-gradient(900px_500px_at_0%_0%,var(--tt-primary-100),transparent_60%),radial-gradient(700px_500px_at_100%_100%,var(--tt-primary-200),transparent_60%)] p-4 sm:p-6"
    >
      <div className="grid w-full max-w-[520px] overflow-hidden rounded-[28px] bg-surface shadow-card lg:min-h-[640px] lg:max-w-[1120px] lg:grid-cols-[1fr_1.05fr]">
        <section className="flex flex-col px-6 py-7 sm:px-8 lg:px-14 lg:py-10">
          <header className="flex items-center justify-between">
            <Logo />
            <ThemeToggle />
          </header>
          <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center pt-8 pb-2">
            <h1 className="mb-1.5 text-[28px] font-extrabold tracking-tight text-ink sm:text-3xl">{title}</h1>
            {subtitle && <p className="mb-7 text-[15px] text-muted">{subtitle}</p>}
            {children}
          </div>
        </section>
        <aside className="hidden p-4 lg:block" aria-hidden>
          <div className="flex h-full flex-col items-center justify-center rounded-[20px] bg-linear-160 from-primary-100 to-primary-200 p-8 text-center">
            <TaskIllustration className="h-auto w-full max-w-[470px]" />
            <h2 className="mt-3 mb-2 text-2xl font-extrabold tracking-tight text-ink">Plan it. Track it. Done.</h2>
            <p className="mx-auto max-w-[340px] text-[14.5px] leading-relaxed text-muted">
              Tasks, reviews and time, organized in one calm workspace.
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
