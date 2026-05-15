/**
 * Tauri build shim — webpack swaps this in for route.ts when TAURI=1.
 *
 * The API proxy is never called in Tauri builds: the frontend uses
 * NEXT_PUBLIC_API_BASE_URL to talk directly to the FastAPI sidecar.
 * This file exists solely to satisfy Next.js's output: "export" constraint,
 * which requires all route handlers to opt out of dynamic rendering.
 */
export const dynamic = "force-static";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function generateStaticParams(): any[] {
  return [{ path: ["index"] }];
}

import { NextResponse } from "next/server";

const stub = () => new NextResponse(null, { status: 404 });
export const GET    = stub;
export const POST   = stub;
export const PATCH  = stub;
export const DELETE = stub;
export const PUT    = stub;
