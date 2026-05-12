"use client";

import { useResizablePanel } from "@/lib/hooks/use-resizable-panel";
import { useFocusMode } from "@/lib/focus/context";
import { FocusToggle } from "@/components/focus/focus-toggle";
import { PageTree } from "@/components/documents/page-tree";

export default function DocumentsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { width, startResize } = useResizablePanel({
    defaultWidth: 240,
    minWidth: 160,
    maxWidth: 480,
    storageKey: "ld-doc-tree-width",
  });
  const { focused } = useFocusMode();

  return (
    <div className="flex flex-col h-full min-h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-end px-3 h-9 border-b shrink-0 bg-background">
        <FocusToggle />
      </div>

      {/* Main row */}
      <div className="flex flex-1 min-h-0">
        {/* Document tree sidebar — collapses in focus mode */}
        <aside
          className="shrink-0 border-r flex flex-col overflow-hidden transition-[width,opacity] duration-300 ease-in-out"
          style={{ width: focused ? 0 : width, opacity: focused ? 0 : 1 }}
        >
          <PageTree />
        </aside>

        {/* Resize handle — hidden in focus mode */}
        <div
          className="shrink-0 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-[width] duration-300 ease-in-out"
          style={{ width: focused ? 0 : 4 }}
          onMouseDown={startResize}
        />

        {/* Main content */}
        <main className="flex-1 min-w-0 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
