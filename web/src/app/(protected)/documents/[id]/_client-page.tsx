"use client";

import dynamic from "next/dynamic";
import { useSegmentId } from "@/lib/hooks/use-segment-id";
import { useAuth } from "@/lib/auth/context";

const DocumentEditor = dynamic(
  () =>
    import("@/components/documents/document-editor").then(
      (m) => m.DocumentEditor
    ),
  { ssr: false }
);

export default function DocumentPage() {
  const id = useSegmentId();
  const { user } = useAuth();
  // Key includes the user ID so the editor fully remounts when switching users,
  // clearing any local state that might have been populated from the previous
  // user's (potentially private) document content.
  return <DocumentEditor key={`${user?.id ?? "anon"}-${id}`} documentId={id} />;
}
