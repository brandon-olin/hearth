"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "./auth/context";
import { ThemeCustomizerProvider } from "./theme/context";
import { SidebarConfigProvider, FolderOpenProvider } from "./sidebar/context";
import { PreferencesSyncer } from "./preferences-syncer";

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
              {/* Syncs theme + sidebar to/from user.preferences in DB */}
              <PreferencesSyncer />
              {children}
            </AuthProvider>
          </QueryClientProvider>
          </FolderOpenProvider>
        </SidebarConfigProvider>
      </ThemeCustomizerProvider>
    </ThemeProvider>
  );
}
