/**
 * Catch-all API proxy — forwards all /api/* requests to the FastAPI backend.
 * Parses the path directly from the URL to avoid depending on the params API.
 *
 * In Tauri static-export builds this route is never called (the frontend talks
 * directly to the sidecar via NEXT_PUBLIC_API_BASE_URL).  next.config.ts swaps
 * this file for route.static.ts at build time when TAURI=1, so the
 * output: "export" constraint is satisfied without affecting the dev proxy.
 */

// force-dynamic ensures Next.js never strips request headers (auth tokens,
// cookies) from the incoming request — required on Node.js 25 where
// force-static wraps Request in a Proxy that silently drops header reads.
export const dynamic = "force-dynamic";

import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:1338";

async function proxy(request: NextRequest, method: string): Promise<NextResponse> {
  // Strip the leading /api prefix to get the backend path.
  const backendPath = request.nextUrl.pathname.replace(/^\/api/, "");
  const search = request.nextUrl.search;
  const targetUrl = `${API_URL}${backendPath}${search}`;

  const headers: Record<string, string> = {
    "content-type": request.headers.get("content-type") ?? "application/json",
  };

  const auth = request.headers.get("authorization");
  if (auth) headers["authorization"] = auth;

  const cookie = request.headers.get("cookie");
  if (cookie) headers["cookie"] = cookie;

  const init: RequestInit = { method, headers };
  if (!["GET", "HEAD"].includes(method)) {
    // Use arrayBuffer to preserve binary data (e.g. image uploads).
    // request.text() re-encodes bytes as UTF-8, corrupting non-text payloads.
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(targetUrl, init);
  const responseHeaders = new Headers();

  const ct = upstream.headers.get("content-type") ?? "";
  if (ct) responseHeaders.set("content-type", ct);

  // Forward Set-Cookie so httpOnly refresh cookies propagate correctly.
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") responseHeaders.append("set-cookie", value);
  });

  // SSE / streaming responses — pipe the body through without buffering.
  // Using upstream.text() would block until the stream closes, killing streaming UX.
  if (ct.includes("text/event-stream") && upstream.body) {
    responseHeaders.set("cache-control", "no-cache");
    responseHeaders.set("connection", "keep-alive");
    responseHeaders.set("x-accel-buffering", "no");
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  }

  // 204 / 205 are "null body" statuses — the Response constructor rejects any
  // body (even an empty string) for these codes per the Fetch spec.
  if (upstream.status === 204 || upstream.status === 205) {
    return new NextResponse(null, { status: upstream.status, headers: responseHeaders });
  }

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest)    { return proxy(req, "GET"); }
export async function POST(req: NextRequest)   { return proxy(req, "POST"); }
export async function PATCH(req: NextRequest)  { return proxy(req, "PATCH"); }
export async function DELETE(req: NextRequest) { return proxy(req, "DELETE"); }
export async function PUT(req: NextRequest)    { return proxy(req, "PUT"); }
