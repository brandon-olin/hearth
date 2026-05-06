import { PageTree } from "@/components/documents/page-tree";

export default function DocumentsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-full">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r flex flex-col overflow-hidden">
        <PageTree />
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 overflow-auto">{children}</main>
    </div>
  );
}
