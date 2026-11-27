"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { type ReactNode, useState } from "react";
import { toast, Toaster } from "sonner";

import { ApiError, errorMessage } from "@/lib/api/errors";
import { SessionProvider } from "@/lib/auth/session";

function makeClient() {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        // Background refetch failures surface as a toast; first loads show inline errors.
        if (query.state.data !== undefined) toast.error(errorMessage(error));
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _vars, _ctx, mutation) => {
        if (!mutation.meta?.silent) toast.error(errorMessage(error));
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <SessionProvider>{children}</SessionProvider>
        <Toaster richColors closeButton position="top-right" toastOptions={{ className: "font-sans" }} />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
