"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "./auth/context";
import { ThemeCustomizerProvider } from "./theme/context";
import { SidebarConfigProvider, FolderOpenProvider } from "./sidebar/context";
import { PreferencesSyncer } from "./preferences-syncer";
import { SetupGuard } from "@/components/setup/setup-guard";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // The API client middleware handles one silent token-refresh retry
            // on 401. Don't let React Query pile on additional retries.
            retry: (failureCount, error) => {
              if (
                error instanceof Error &&
                (error.message.startsWith("401:") ||
                  error.message.startsWith("403:"))
              )
                return false;
              return failureCount < 2;
            },
            // 30-second stale time: all data from a localhost API is fast to
            // fetch, so there's no need to treat every cached result as
            // immediately stale. This prevents redundant refetches when
            // navigating back to a page you visited in the last half-minute.
            staleTime: 30_000,
            // In a desktop app, regaining window focus is a constant event
            // (e.g. clicking back from another app). Disable the default
            // behavior of refetching all active queries on focus — it causes
            // a wave of requests every time the user alt-tabs back.
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <ThemeCustomizerProvider>
        <SidebarConfigProvider>
          <FolderOpenProvider>
            <QueryClientProvider client={queryClient}>
              <AuthProvider>
                <SetupGuard>
                  {/* Syncs theme + sidebar to/from user.preferences in DB */}
                  <PreferencesSyncer />
                  {children}
                </SetupGuard>
              </AuthProvider>
            </QueryClientProvider>
          </FolderOpenProvider>
        </SidebarConfigProvider>
      </ThemeCustomizerProvider>
    </ThemeProvider>
  );
}
