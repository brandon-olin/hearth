"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

const DocumentEditor = dynamic(
  () =>
    import("@/components/documents/document-editor").then(
      (m) => m.DocumentEditor
    ),
  { ssr: false }
);

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  return <DocumentEditor documentId={id} />;
}
