import { FileText } from "lucide-react";

export default function DocumentsIndexPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center px-6">
      <FileText className="h-10 w-10 text-muted-foreground/40 mb-4" />
      <p className="text-sm text-muted-foreground">
        Select a page from the sidebar, or create a new one.
      </p>
    </div>
  );
}
