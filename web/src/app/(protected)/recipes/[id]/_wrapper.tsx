"use client";

import dynamic from "next/dynamic";

const ClientPage = dynamic(() => import("./_client-page"), { ssr: false });

export default function Wrapper() {
  return <ClientPage />;
}
