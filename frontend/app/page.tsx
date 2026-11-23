"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { FullScreenLoader } from "@/components/layout/app-shell";
import { homeFor } from "@/components/layout/nav";
import { useSession } from "@/lib/auth/session";

export default function Home() {
  const { status, user } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
    else if (status === "authenticated" && user) router.replace(homeFor(user));
  }, [status, user, router]);
  return <FullScreenLoader />;
}
